"""Servidor de VerdeH3: el mapa (tiempo real, corredor Dijkstra, histórico) y la captura en terreno desde el teléfono.

    python -m terreno.servidor --puerto 8000          # 34 comunas; el corredor se calcula en las elegidas
    cloudflared tunnel --url http://localhost:8000      # HTTPS público: el GPS del teléfono lo exige

Teléfono: https://<túnel>/?k=<clave>   ·   Mapa para proyectar: http://localhost:8000/mapa
El mapa filtra por comuna, distrito (barrio H3 res 7) o una zona dibujada, mueve presupuesto y pesos del
corredor, y muestra la serie histórica satelital (data/historico_h3.parquet). Si existe data/live_h3.parquet
(sensores en vivo, Rol 2) entra al calor de la urgencia; se relee cuando cambia.
Si TERRENO_CLAVE (o --clave) está definida, subir fotos exige ?k=<clave>, porque la URL del túnel es pública.
Solo cuentan las fotos que Claude valida como exteriores de calle; sin Claude quedan «sin validar» y no cambian
el corredor, salvo con --aceptar-sin-validar (demo sin red).
Credenciales de Claude: ANTHROPIC_API_KEY, un perfil de `ant auth login`, o la clave sola en el archivo
.anthropic_key en la raíz del repo (está en .gitignore; nunca la subas).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import h3
import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from optimizer import solve_corridor
from terreno.almacen import Almacen, cuenta, estado_validacion
from terreno.vision import analizar

ESTATICO = Path(__file__).resolve().parent / "static"
MAX_FOTO_BYTES = 15 * 1024 * 1024
FOTO_OK = re.compile(r"^[0-9T]{15}-[0-9a-f]{6}(_min)?\.jpg$")
VIDEO_OK = re.compile(r"^[0-9T]{15}-[0-9a-f]{6}\.(webm|mp4|mov)$")
MAX_VIDEO_BYTES = 80 * 1024 * 1024
MAX_CUADROS_RECIBIDOS = 40
MAX_CUADROS_ANALIZADOS = 12   # cada cuadro analizado es una llamada a Claude
CUADROS_POR_HEX = 2
EXT_VIDEO = {"video/webm": "webm", "video/mp4": "mp4", "video/quicktime": "mov"}
log = logging.getLogger("terreno")


def _resumen(r: dict) -> dict:
    return {"hexes": len(r["hexes"]), "km": round(r["length_km"], 2),
            "urgencia_cubierta": round(r["urgencia_cubierta"], 3), "urgencia_azar": round(r["urgencia_azar"], 3),
            "personas_cubiertas": r["personas_cubiertas"], "verificados": r.get("verificados", 0)}


def _num(x, lo=None, hi=None):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v or (lo is not None and v < lo) or (hi is not None and v > hi):
        return None
    return v


def _punto(p: dict) -> dict | None:
    """Punto GPS del teléfono, solo con campos conocidos y en rango."""
    lat, lon = _num(p.get("lat"), -90, 90), _num(p.get("lon"), -180, 180)
    if lat is None or lon is None:
        return None
    return {"lat": lat, "lon": lon, "precision_m": _num(p.get("precision_m"), 0), "t_s": _num(p.get("t_s"), 0),
            "tomado_en": p.get("tomado_en") if isinstance(p.get("tomado_en"), str) else None}


def elegir_cuadros(cuadros: list[dict], maximo: int = MAX_CUADROS_ANALIZADOS) -> list[int]:
    """Índices de cuadros a analizar: hasta CUADROS_POR_HEX por hexágono, primero uno por hexágono (en orden)."""
    grupos: dict[str, list[int]] = {}
    for i, c in enumerate(cuadros):
        grupos.setdefault(h3.latlng_to_cell(c["lat"], c["lon"], 9), []).append(i)
    rondas = [[g[0] for g in grupos.values()],
              [g[len(g) // 2] for g in grupos.values() if len(g) > 1]]  # el del medio de su tramo
    elegidos: list[int] = []
    for ronda in rondas[:CUADROS_POR_HEX]:
        for i in ronda:
            if len(elegidos) < maximo and i not in elegidos:
                elegidos.append(i)
    return sorted(elegidos)


class Seleccion(BaseModel):
    """Cambio de análisis desde el mapa. Lo que no viene se mantiene; zona=null o [] la borra."""
    comunas: list[str] | None = None
    distritos: list[str] | None = None   # nombres «Comuna - Distrito N» de las comunas elegidas; vacío = todos
    zona: list[str] | None = None        # hexágonos encerrados con el mouse
    km: float | None = None
    w_calor: float | None = None
    w_arbol: float | None = None
    w_personas: float | None = None


def distritos(df: pd.DataFrame) -> dict[tuple[str, str], str]:
    """Nombre «Comuna - Distrito N» por (comuna, h3_padre): de norte a sur y de oeste a este dentro de cada
    comuna. Un barrio res 7 puede cruzar el límite comunal: cada comuna nombra su parte."""
    padres = (df[["comuna", "h3_padre", "lat", "lon"]].groupby(["comuna", "h3_padre"], as_index=False).mean()
              .sort_values(["comuna", "lat", "lon"], ascending=[True, False, True]))
    padres["num"] = padres.groupby("comuna").cumcount() + 1
    return dict(zip(zip(padres["comuna"], padres["h3_padre"]), padres["comuna"] + " - Distrito " + padres["num"].astype(str)))


def _r(x, n=2):
    return None if x is None or x != x else round(float(x), n)


def _comunas_geo(df: pd.DataFrame) -> dict:
    """Contorno de cada comuna (unión de sus hexágonos) como anillos [[lat, lon], ...] para Leaflet."""
    geo = {}
    for comuna, hs in df.groupby("comuna")["h3_index"]:
        g = h3.h3shape_to_geo(h3.cells_to_h3shape(list(hs)))
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        geo[comuna] = [[[[round(la, 5), round(lo, 5)] for lo, la in anillo] for anillo in poly] for poly in polys]
    return geo


def _vecinas(df: pd.DataFrame) -> dict[str, list[str]]:
    """Comunas que comparten borde: algún hexágono de una toca uno de la otra."""
    comuna = dict(zip(df["h3_index"], df["comuna"]))
    pares: dict[str, set[str]] = {c: set() for c in df["comuna"].unique()}
    for h, c in comuna.items():
        for v in h3.grid_ring(h, 1):
            cv = comuna.get(v)
            if cv and cv != c:
                pares[c].add(cv)
    return {c: sorted(v) for c, v in pares.items()}


def crear_app(datos: Path = Path("data/santiago_h3_gs.parquet"), data_dir: Path = Path("data"),
              km: float = 3.0, clave: str | None = None, usar_claude: bool = True,
              aceptar_sin_validar: bool = False, comunas: list[str] | None = None) -> FastAPI:
    df = pd.read_parquet(datos)
    nombres = distritos(df)
    df["distrito"] = [nombres[k] for k in zip(df["comuna"], df["h3_padre"])]
    alm = Almacen(data_dir, aceptar_sin_validar)
    ruta_live, ruta_hist = Path(data_dir) / "live_h3.parquet", Path(data_dir) / "historico_h3.parquet"
    ruta_meta = Path(data_dir) / "historico_meta.json"
    hist: dict = {}
    hex_area = set(df["h3_index"])
    comuna_de = dict(zip(df["h3_index"], df["comuna"]))
    todas = sorted(df["comuna"].unique())
    vecinas = _vecinas(df)
    geo = _comunas_geo(df)
    poligonos = {h: [[round(la, 6), round(lo, 6)] for la, lo in h3.cell_to_boundary(h)] for h in df["h3_index"]}
    distritos_de = {c: set(v) for c, v in df.groupby("comuna")["distrito"].unique().items()}
    lst_hoy = df["lst_c_ultima"].fillna(df["lst_c"]) if "lst_c_ultima" in df else df["lst_c"]
    copa = df["copa_modelo_pct"] if "copa_modelo_pct" in df else df["arbol_pct"]
    lock = threading.Lock()
    estado: dict = {"version": 0, "sel_id": 0, "live_mtime": None, "live": None,
                    "p": {"comunas": [], "distritos": [], "zona": None, "km": km, "w": (0.4, 0.4, 0.2)}}

    def leer_live() -> bool:
        """Relee data/live_h3.parquet si cambió. Devuelve si cambió."""
        mt = ruta_live.stat().st_mtime if ruta_live.exists() else None
        if mt == estado["live_mtime"]:
            return False
        try:
            estado["live"] = pd.read_parquet(ruta_live) if mt else None
        except Exception:
            log.warning("No se pudo leer %s", ruta_live)
            estado["live"] = None
        estado["live_mtime"] = mt
        return True

    def resolver(terreno=None):
        p = estado["p"]
        return solve_corridor(estado["sub"], p["km"], *p["w"], live=estado["live"], terreno=terreno)

    def elegir(cambio: Seleccion):
        """Fija el área (comunas → distritos → zona), presupuesto y pesos, y la línea base sin terreno («antes»)."""
        p = dict(estado["p"])
        if cambio.comunas is not None:
            if set(cambio.comunas) - set(todas):
                raise HTTPException(422, "Comuna desconocida")
            p["comunas"] = [c for c in todas if c in set(cambio.comunas)]
        validos = set().union(*(distritos_de[c] for c in p["comunas"]))
        if cambio.distritos is not None:
            p["distritos"] = sorted(set(cambio.distritos) & validos)
        else:
            p["distritos"] = [d for d in p["distritos"] if d in validos]
        if "zona" in cambio.model_fields_set:
            p["zona"] = sorted(set(cambio.zona) & hex_area) if cambio.zona else None
        if cambio.km is not None:
            if not 0.5 <= cambio.km <= 30:
                raise HTTPException(422, "Presupuesto entre 0,5 y 30 km")
            p["km"] = cambio.km
        w = [x if x is not None else old for x, old in zip((cambio.w_calor, cambio.w_arbol, cambio.w_personas), p["w"])]
        if min(w) < 0 or sum(w) <= 0:
            raise HTTPException(422, "Pesos >= 0 y no todos 0")
        p["w"] = tuple(w)
        sub = df[df["comuna"].isin(p["comunas"])]
        if p["distritos"]:
            sub = sub[sub["distrito"].isin(p["distritos"])]
        if p["zona"]:
            en_zona = sub[sub["h3_index"].isin(p["zona"])]
            if len(en_zona):  # como en la app de Rol 3: una zona fuera del área no la vacía
                sub = en_zona
        anterior = estado.get("area")
        estado["p"], estado["sub"] = p, sub
        estado["area"] = tuple(sub.index)
        if estado["area"] != anterior:
            estado["sel_id"] += 1
        estado["antes"] = resolver()

    def recalcular():
        terreno = alm.escribir_h3() if alm.capturas() else None
        estado["terreno"] = terreno
        estado["ahora"] = resolver(terreno)
        estado["version"] += 1

    def revisar_live():
        if leer_live():
            estado["antes"] = resolver()
            recalcular()

    inicial = comunas or todas  # al abrir se ven todas; el mapa permite separar por comuna
    faltan = set(inicial) - set(todas)
    if faltan:
        raise ValueError(f"Comunas que no están en {datos}: {sorted(faltan)}")
    leer_live()
    elegir(Seleccion(comunas=inicial))
    recalcular()
    app = FastAPI(title="VerdeH3")

    def revisar_clave(k: str | None):
        if clave and k != clave:
            raise HTTPException(403, "Clave incorrecta: abre la página con ?k=<clave>")

    @app.get("/")
    def captura_html():
        return FileResponse(ESTATICO / "captura.html")

    @app.get("/mapa")
    def mapa_html():
        return FileResponse(ESTATICO / "mapa.html")

    @app.post("/api/captura")
    def captura(foto: UploadFile = File(...), lat: float = Form(...), lon: float = Form(...),
                precision_m: float | None = Form(None), rumbo: float | None = Form(None),
                nota: str = Form(""), tomado_en: str | None = Form(None), k: str | None = Query(None)):
        revisar_clave(k)
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise HTTPException(422, "Coordenadas fuera de rango")
        datos_foto = foto.file.read(MAX_FOTO_BYTES + 1)
        if len(datos_foto) > MAX_FOTO_BYTES:
            raise HTTPException(413, "Foto de más de 15 MB")
        try:
            obs = analizar(datos_foto, usar_claude)
        except Exception:
            raise HTTPException(422, "No se pudo leer la imagen")
        with lock:
            previo = estado["ahora"]
            cap = alm.guardar(datos_foto, lat, lon, precision_m, rumbo, nota, obs, tomado_en)
            recalcular()
            ahora = estado["ahora"]
        return {
            "captura": cap,
            "validacion": estado_validacion(cap),
            "cuenta": cuenta(cap, aceptar_sin_validar),
            "fuera_de_area": cap["h3_index"] not in hex_area,
            "comuna": comuna_de.get(cap["h3_index"]),
            "fuera_de_seleccion": cap["h3_index"] not in set(estado["sub"]["h3_index"]),
            "en_corredor": cap["h3_index"] in ahora["hexes"],
            "corredor_cambio": set(previo["hexes"]) != set(ahora["hexes"]),
            "antes": _resumen(estado["antes"]), "previo": _resumen(previo), "ahora": _resumen(ahora),
        }

    @app.post("/api/video")
    def subir_video(cuadros: list[UploadFile] = File(...), meta: str = Form(...),
                    video: UploadFile | None = File(None), k: str | None = Query(None)):
        """Video grabado en la página: cuadros JPEG con su posición y hora, más el trazado GPS del recorrido."""
        revisar_clave(k)
        try:
            m = json.loads(meta)
            info = [_punto(c) for c in m["cuadros"]]
            track = [x for x in (_punto(p) for p in m.get("track", [])[:5000]) if x]
        except (ValueError, KeyError, TypeError, AttributeError):
            raise HTTPException(422, "meta inválido")
        if not cuadros or len(cuadros) != len(info) or len(cuadros) > MAX_CUADROS_RECIBIDOS:
            raise HTTPException(422, f"Entre 1 y {MAX_CUADROS_RECIBIDOS} cuadros, cada uno con su posición")
        validos = [i for i, c in enumerate(info) if c]
        if not validos:
            raise HTTPException(422, "Ningún cuadro trae posición GPS")
        vbytes, ext = None, None
        if video is not None:
            ext = EXT_VIDEO.get((video.content_type or "").split(";")[0])
            if ext is None:
                raise HTTPException(415, "Formato de video no soportado (webm, mp4 o mov)")
            vbytes = video.file.read(MAX_VIDEO_BYTES + 1)
            if len(vbytes) > MAX_VIDEO_BYTES:
                raise HTTPException(413, "Video de más de 80 MB")
        sel = [validos[i] for i in elegir_cuadros([info[i] for i in validos])]
        imgs = [cuadros[i].file.read(MAX_FOTO_BYTES + 1) for i in sel]

        def analizar_seguro(b):
            try:
                return analizar(b, usar_claude) if len(b) <= MAX_FOTO_BYTES else None
            except Exception:
                return None

        with ThreadPoolExecutor(4) as ex:
            resultados = list(ex.map(analizar_seguro, imgs))
        with lock:
            previo = estado["ahora"]
            rec = alm.guardar_video(vbytes, ext, m.get("inicio"), track, len(sel), str(m.get("nota", "")))
            caps = []
            for i, img, obs in zip(sel, imgs, resultados):
                if obs is None:
                    continue
                c = info[i]
                caps.append(alm.guardar(img, c["lat"], c["lon"], c["precision_m"], None, "", obs, c["tomado_en"],
                                        extra={"video_id": rec["id"], "t_video_s": c["t_s"]}))
            recalcular()
            ahora = estado["ahora"]
        estados = [estado_validacion(c) for c in caps]
        return {
            "recorrido": {k2: rec[k2] for k2 in ("id", "inicio", "duracion_s", "archivo")},
            "cuadros_recibidos": len(cuadros), "cuadros_analizados": len(caps),
            "validos": estados.count("valida"), "descartados": estados.count("descartada"),
            "sin_validar": estados.count("sin_validar"),
            "hexagonos": sorted({c["h3_index"] for c in caps if cuenta(c, aceptar_sin_validar)}),
            "fuera_de_area": sum(c["h3_index"] not in hex_area for c in caps),
            "fuera_de_seleccion": sum(c["h3_index"] not in set(estado["sub"]["h3_index"]) for c in caps),
            "motivos_descarte": sorted({c.get("motivo_rechazo", "") for c in caps if c.get("valida") is False} - {""}),
            "corredor_cambio": set(previo["hexes"]) != set(ahora["hexes"]),
            "antes": _resumen(estado["antes"]), "previo": _resumen(previo), "ahora": _resumen(ahora),
        }

    def es_local(request: Request) -> bool:
        """El mapa abierto en el mismo computador (no por el túnel, que agrega cf-connecting-ip)."""
        return (request.client is not None and request.client.host in ("127.0.0.1", "::1", "testclient")
                and "cf-connecting-ip" not in request.headers)

    def _parametros() -> dict:
        p = estado["p"]
        return {"comunas": p["comunas"], "distritos": p["distritos"], "zona": len(p["zona"] or []),
                "km": p["km"], "w_calor": p["w"][0], "w_arbol": p["w"][1], "w_personas": p["w"][2]}

    dist_por_comuna = {c: sorted(v, key=lambda n: int(n.rsplit(" ", 1)[1])) for c, v in distritos_de.items()}

    @app.get("/api/salud")
    def salud():
        return {"ok": True}

    @app.get("/api/comunas")
    def api_comunas():
        return {"comunas": todas, "vecinas": vecinas, "geo": geo, "distritos": dist_por_comuna,
                "seleccion": estado["p"]["comunas"], "parametros": _parametros()}

    @app.post("/api/seleccion")
    def api_seleccion(request: Request, cambio: Seleccion, k: str | None = Query(None)):
        """Cambia área, presupuesto o pesos. Desde el mismo computador no pide clave; por el túnel sí."""
        if not es_local(request):
            revisar_clave(k)
        with lock:
            elegir(cambio)
            recalcular()
            return {"seleccion": estado["p"]["comunas"], "parametros": _parametros(),
                    "antes": _resumen(estado["antes"]), "ahora": _resumen(estado["ahora"])}

    @app.get("/api/version")
    def api_version():
        """Sondeo barato del mapa: cambia con cada captura, video, selección o lectura en vivo nueva."""
        with lock:
            revisar_live()
            return {"version": estado["version"], "sel_id": estado["sel_id"]}

    @app.get("/api/estado")
    def api_estado(sel_id: int | None = Query(None)):
        """Hexágonos del área en columnas. Los polígonos solo van si el mapa no tiene los de esta área (sel_id)."""
        with lock:
            revisar_live()
            ahora, terreno, antes, sub, live = (estado[x] for x in ("ahora", "terreno", "antes", "sub", "live"))
            version, sid, params = estado["version"], estado["sel_id"], _parametros()
            caps = [{**c, "validacion": estado_validacion(c), "cuenta": cuenta(c, aceptar_sin_validar)}
                    for c in alm.capturas()]
        verif = set(terreno["h3_index"]) if terreno is not None else set()
        en_antes, en_ahora = set(antes["hexes"]), set(ahora["hexes"])
        vivo = pd.Series(float("nan"), index=sub.index)
        if live is not None and len(live):
            ok = live[live["confianza"].isin(["alta", "media"]) & live["temp_aire_c"].notna()]
            vivo = sub["h3_padre"].map(ok.groupby("h3_padre")["temp_aire_c"].last())
        hs = sub["h3_index"].tolist()
        col = {
            "h": hs, "comuna": sub["comuna"].tolist(), "distrito": sub["distrito"].tolist(),
            "u": [_r(u, 3) for u in ahora["urgencia"]],
            "lst": [_r(x, 1) for x in lst_hoy.loc[sub.index]], "vivo": [_r(x, 1) for x in vivo],
            "ndvi": [_r(x, 3) for x in sub["ndvi"]], "copa": [_r(x, 1) for x in copa.loc[sub.index]],
            "pob": sub["poblacion"].astype(int).tolist(), "social": [_r(x, 3) for x in sub["social"]],
            "parque": sub["es_parque"].astype(bool).tolist(),
            "antes": [h in en_antes for h in hs], "ahora": [h in en_ahora for h in hs],
            "verificado": [h in verif for h in hs],
        }
        if sel_id != sid:
            col["pol"] = [poligonos[h] for h in hs]
        recorridos = [{"id": r["id"], "inicio": r.get("inicio"), "duracion_s": r.get("duracion_s"),
                       "archivo": r.get("archivo"), "linea": [[p["lat"], p["lon"]] for p in r.get("track", [])]}
                      for r in alm.recorridos()]
        return {"version": version, "sel_id": sid, "seleccion": params["comunas"], "parametros": params,
                "hex": col, "capturas": caps, "recorridos": recorridos, "en_vivo": live is not None,
                "antes": {**_resumen(antes), "personas_azar": antes["personas_azar"]},
                "ahora": {**_resumen(ahora), "personas_azar": ahora["personas_azar"]}}

    @app.get("/api/historico")
    def api_historico(desde: str = Query(...), hasta: str = Query(...)):
        """Promedio por hexágono de LST y NDVI de las escenas entre dos fechas (YYYY-MM-DD), para el área actual."""
        try:
            d0, d1 = pd.Timestamp(desde), pd.Timestamp(hasta)
        except ValueError:
            raise HTTPException(422, "Fechas YYYY-MM-DD")
        if d0 > d1:
            raise HTTPException(422, "«Desde» debe ser anterior o igual a «Hasta»")
        if "df" not in hist:
            if not ruta_hist.exists():
                raise HTTPException(404, "No hay data/historico_h3.parquet")
            hist["df"] = pd.read_parquet(ruta_hist)
            hist["meta"] = json.loads(ruta_meta.read_text(encoding="utf-8")) if ruta_meta.exists() else {}
        with lock:
            hs = set(estado["sub"]["h3_index"])
        h = hist["df"]
        sub_h = h[(h["fecha"] >= d0) & (h["fecha"] < d1 + pd.Timedelta(days=1)) & h["h3_index"].isin(hs)]
        prom = sub_h.groupby("h3_index")[["lst_c", "ndvi"]].mean()
        m = hist["meta"]
        return {"meses": int(sub_h["mes"].nunique()), "h": prom.index.tolist(),
                "lst": [_r(x, 1) for x in prom["lst_c"]], "ndvi": [_r(x, 3) for x in prom["ndvi"]],
                "meta": {k2: m.get(k2) for k2 in ("meses_totales", "mes_min", "mes_max", "escenas_landsat",
                                                   "escenas_sentinel2")}}

    @app.get("/videos/{nombre}")
    def videos(nombre: str):
        if not VIDEO_OK.match(nombre) or not (alm.videos / nombre).exists():
            raise HTTPException(404)
        return FileResponse(alm.videos / nombre)

    @app.get("/fotos/{nombre}")
    def fotos(nombre: str):
        if not FOTO_OK.match(nombre) or not (alm.fotos / nombre).exists():
            raise HTTPException(404)
        return FileResponse(alm.fotos / nombre, media_type="image/jpeg")

    return app


def cargar_clave_anthropic(archivo: Path) -> bool:
    """Si no hay ANTHROPIC_API_KEY en el entorno, la lee de un archivo local. Devuelve si quedó definida."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    if archivo.exists():
        clave = archivo.read_text(encoding="utf-8-sig").strip()
        if clave:
            os.environ["ANTHROPIC_API_KEY"] = clave
            return True
    return False


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--datos", type=Path, default=Path("data/santiago_h3_gs.parquet"))
    p.add_argument("--comunas", nargs="+", help="comunas iniciales (por defecto todas; luego se eligen en el mapa)")
    p.add_argument("--data", type=Path, default=Path("data"), help="dónde guardar capturas y terreno_h3.parquet")
    p.add_argument("--km", type=float, default=3.0)
    p.add_argument("--puerto", type=int, default=int(os.environ.get("PORT", 8000)))
    p.add_argument("--host", default="127.0.0.1", help="127.0.0.1 basta para cloudflared; 0.0.0.0 abre la red local")
    p.add_argument("--clave", default=os.environ.get("TERRENO_CLAVE"))
    p.add_argument("--sin-claude", action="store_true", help="solo índice de verde, sin llamar a Claude")
    p.add_argument("--archivo-clave", type=Path, default=Path(".anthropic_key"),
                   help="archivo con la API key de Anthropic, si no está en ANTHROPIC_API_KEY")
    p.add_argument("--aceptar-sin-validar", action="store_true",
                   help="las fotos sin validar (sin Claude) también cambian el corredor; solo para demos sin red")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO)
    if not a.sin_claude:
        log.info("Claude: %s", "API key encontrada" if cargar_clave_anthropic(a.archivo_clave)
                 else "sin API key (se probará un perfil de `ant`; si no hay, fotos sin validar)")
    import uvicorn
    uvicorn.run(crear_app(a.datos, a.data, a.km, a.clave, not a.sin_claude, a.aceptar_sin_validar, a.comunas), host=a.host, port=a.puerto)


if __name__ == "__main__":
    main()
