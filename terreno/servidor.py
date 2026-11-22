"""Servidor de VerdeH3: el mapa (tiempo real, corredor Dijkstra, histórico) y la API del sitio web/.

    python -m terreno.servidor --puerto 8000          # 34 comunas; el corredor se calcula en las elegidas
    cloudflared tunnel --url http://localhost:8000      # HTTPS público: el GPS del teléfono lo exige

Sitio Viridis: si existe web/out (cd web && npm run exportar), se sirve en «/» desde este mismo servidor: un
solo servicio y un solo enlace (así se despliega en Render, ver Dockerfile). Sin web/out, «/» lleva a /mapa.
La página del teléfono se retiró; la API de subida (/api/captura, /api/video, /api/audio) sigue y lo ya
capturado cuenta (biodiversidad por hexágono con el peso w_bio, fotos validadas por Claude).
El mapa filtra por comuna, distrito (barrio H3 res 7) o una zona dibujada, mueve presupuesto y pesos del
corredor, y muestra la serie histórica satelital (data/historico_h3.parquet). Si existe data/live_h3.parquet
(máxima del día por barrio, Rol 2: lo escribe maximas.py cada noche) entra al calor de la urgencia; se relee
cuando cambia. Con REFRESCO_VIVO_MIN > 0 (apagado por omisión), mientras alguien mira el mapa y ese archivo
tiene más de esos minutos, se corre un ciclo de vivo.py (lectura del momento) en otro hilo.
Si TERRENO_CLAVE (o --clave) está definida, subir fotos exige ?k=<clave>, porque la URL del túnel es pública.
Solo cuentan las fotos que Claude valida como exteriores de calle; sin Claude quedan «sin validar» y no cambian
el corredor, salvo con --aceptar-sin-validar (demo sin red).
Credenciales de Claude: ANTHROPIC_API_KEY, un perfil de `ant auth login`, o la clave sola en el archivo
.anthropic_key en la raíz del repo (está en .gitignore; nunca la subas).
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
import logging
import os
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import h3
import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ecologia import ESPECIES, ESPECIES_DE, PERFIL_DE, PERFILES, resolver_corredor_por_especies
from optimizer import PESOS, solve_corridor
from terreno import aves
from terreno.almacen import Almacen, cuenta, estado_validacion, hora
from terreno.vision import analizar

ESTATICO = Path(__file__).resolve().parent / "static"
WEB = Path(__file__).resolve().parent.parent / "web" / "out"   # sitio Viridis exportado (npm run exportar)
MAX_FOTO_BYTES = 15 * 1024 * 1024
FOTO_OK = re.compile(r"^[0-9T]{15}-[0-9a-f]{6}(_min)?\.jpg$")
VIDEO_OK = re.compile(r"^[0-9T]{15}-[0-9a-f]{6}\.(webm|mp4|mov)$")
MAX_VIDEO_BYTES = 80 * 1024 * 1024
MAX_AUDIO_BYTES = 6 * 1024 * 1024    # 15 s de WAV mono 16 bit a 48 kHz son ~1,4 MB
MAX_AUDIO_PASEO = 24 * 1024 * 1024   # 3 min de WAV mono 16 bit a 32 kHz son ~11,5 MB
AUDIO_OK = re.compile(r"^[0-9T]{15}-[0-9a-f]{6}\.wav$")
W_BIO = 0.1                          # peso inicial de la biodiversidad (los otros: optimizer.PESOS)
# Pesos iniciales de cada sesión: calor, árboles, personas, biodiversidad y vulnerabilidad (solo personas).
PESOS_INICIALES = (PESOS["w_calor"], PESOS["w_arbol"], PESOS["w_personas"], W_BIO, PESOS["w_vuln"])
MAX_CUADROS_RECIBIDOS = 40
MAX_CUADROS_ANALIZADOS = 12   # cada cuadro analizado es una llamada a Claude
CUADROS_POR_HEX = 2
EXT_VIDEO = {"video/webm": "webm", "video/mp4": "mp4", "video/quicktime": "mov"}
log = logging.getLogger("terreno")


def _resumen(r: dict) -> dict:
    return {"hexes": len(r["hexes"]), "km": round(r["length_km"], 2),
            "urgencia_cubierta": round(r["urgencia_cubierta"], 3), "urgencia_azar": round(r["urgencia_azar"], 3),
            "personas_cubiertas": r["personas_cubiertas"], "verificados": r.get("verificados", 0),
            "km_min": round(r["km_min"], 2) if r.get("km_min") else None,
            "checkpoints": len(r.get("checkpoints", [])),
            "parques_conectados": r.get("parques_conectados", 0),
            "resistencia_media": r.get("resistencia_media")}


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
    w_bio: float | None = None
    w_vuln: float | None = None          # vulnerabilidad al calor (Censo): solo entra en la urgencia de personas
    vecinas: bool | None = None          # el corredor puede partir o llegar a parques de las comunas vecinas
    perfil: str | None = None            # humanos | fauna_aves | fauna_abejas | mixto (forma antigua de elegir especies)
    especies: list[str] | None = None    # una o más de humanos, aves, abejas: para quién se traza el corredor


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


def sin_islas(df: pd.DataFrame) -> pd.DataFrame:
    """Quita los pedazos sueltos de la grilla que no tienen gente ni parques: son restos del recorte rectangular
    de los datos (un trozo de comuna que queda separado del resto porque la unión pasa por fuera del recorte)."""
    todos, comp = set(df["h3_index"]), {}
    for h in df["h3_index"]:
        if h in comp:
            continue
        comp[h], pila = h, [h]
        while pila:
            for v in h3.grid_disk(pila.pop(), 1):
                if v in todos and v not in comp:
                    comp[v] = h
                    pila.append(v)
    grupo = df["h3_index"].map(comp)
    por = df.groupby(grupo).agg(n=("h3_index", "size"), pob=("poblacion", "sum"), parques=("es_parque", "sum"))
    fuera = por.index[(por["n"] < por["n"].max()) & (por["pob"] == 0) & (por["parques"] == 0)]
    return df[~grupo.isin(fuera)]


def crear_app(datos: Path = Path("data/santiago_h3_gs.parquet"), data_dir: Path = Path("data"),
              km: float = 3.0, clave: str | None = None, usar_claude: bool = True,
              aceptar_sin_validar: bool = False, comunas: list[str] | None = None,
              web: Path | None = WEB) -> FastAPI:
    df = sin_islas(pd.read_parquet(datos))
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
    # El mapa muestra la misma escena de verano que usa el índice (optimizer.urgencia usa lst_c), con su fecha;
    # las escenas más nuevas están en el histórico.
    lst_hoy = df["lst_c"]
    lst_fecha = df["lst_fecha"].mode().iat[0] if "lst_fecha" in df and df["lst_fecha"].notna().any() else None
    copa = df["copa_modelo_pct"] if "copa_modelo_pct" in df else df["arbol_pct"]
    # Fecha de la imagen con que el modelo predice la copa (data/modelo_copa.json), para mostrarla en la página.
    ruta_copa = Path(datos).with_name("modelo_copa.json")
    try:
        copa_fecha = json.loads(ruta_copa.read_text(encoding="utf-8"))["pasadas"]["actual"] if ruta_copa.exists() else None
    except (ValueError, KeyError, TypeError):
        copa_fecha = None
    lock = threading.Lock()
    refresco_s = float(os.getenv("REFRESCO_VIVO_MIN", "0")) * 60
    if Path(data_dir).resolve() != Path("data").resolve():
        refresco_s = 0  # vivo.py escribe en ./data
    # `estado` guarda lo que es de todos (capturas en terreno, lectura en vivo) y además es la sesión por defecto,
    # la que usan el mapa antiguo y el teléfono. Cada navegador de la página Next tiene su propia sesión (área,
    # presupuesto y pesos) identificada por `s`, que vive solo en memoria y se pierde al recargar la página.
    estado: dict = {"datos": 0, "cambios": 0, "sel_seq": 0, "sel_id": 0, "live_mtime": None, "live": None,
                    "intento_vivo": 0.0, "terreno": None,
                    "p": {"comunas": [], "distritos": [], "zona": None, "km": km, "w": PESOS_INICIALES, "especies": ("humanos",)}}
    sesiones: OrderedDict[str, dict] = OrderedDict()
    MAX_SESIONES = 64

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

    def resolver(st: dict, terreno=None):
        """Corredor de una sesión según su perfil: para personas (optimizer) o para fauna (ecologia)."""
        p = st["p"]
        wc, wa, wp, wb, wv = p["w"]
        especies = frozenset(p.get("especies") or ("humanos",))
        if especies == {"humanos"}:
            r = solve_corridor(st["sub"], p["km"], wc, wa, wp, live=estado["live"], terreno=terreno, w_bio=wb, w_vuln=wv,
                               apoyo=st.get("apoyo"))
            r["checkpoints"] = []
            r["parques_conectados"] = len(r.get("tramos", [])) + 1 if r.get("tramos") else 0
            r["resistencia_media"] = None
            return r
        # Con aves o abejas: conectividad ecológica (sin fotos de terreno); las comunas vecinas valen igual.
        res = resolver_corredor_por_especies(st["sub"], especies, budget_km=p["km"], w_calor=wc, w_arbol=wa,
                                             w_personas=wp, live=estado["live"], apoyo=st.get("apoyo"), w_vuln=wv)
        return {
            "hexes": res["hexes_corredor"],
            "checkpoints": res["hexes_checkpoints"],
            "length_km": res["length_km"],
            "urgencia": res["score_mapa"],
            "urgencia_cubierta": res["urgencia_cubierta"],
            "urgencia_azar": res["urgencia_azar"],
            "personas_cubiertas": res["personas_cubiertas"],
            "personas_azar": res["personas_azar"],
            "tramos": res["tramos"],
            "verificados": 0,
            "fuera": res.get("fuera", []),
            "km_min": res.get("km_min"),
            "parques_conectados": res["parques_conectados"],
            "resistencia_media": round(res["resistencia_media"], 1) if res["resistencia_media"] is not None else None,
        }

    def elegir(cambio: Seleccion, st: dict | None = None):
        """Fija el área (comunas → distritos → zona), presupuesto y pesos de una sesión, y su línea base sin
        terreno («antes»). El corredor con terreno («ahora») lo calcula al_dia()."""
        st = estado if st is None else st
        p = dict(st["p"])
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
        nuevos = (cambio.w_calor, cambio.w_arbol, cambio.w_personas, cambio.w_bio, cambio.w_vuln)
        w = [x if x is not None else old for x, old in zip(nuevos, p["w"])]
        if min(w) < 0 or sum(w) <= 0:
            raise HTTPException(422, "Pesos >= 0 y no todos 0")
        p["w"] = tuple(w)
        if cambio.perfil is not None:
            if cambio.perfil not in PERFILES:
                raise HTTPException(422, "Perfil inválido")
            p["especies"] = ESPECIES_DE[cambio.perfil]
        if cambio.especies is not None:
            if not cambio.especies or set(cambio.especies) - set(ESPECIES):
                raise HTTPException(422, "Especies: una o más de humanos, aves, abejas")
            p["especies"] = tuple(e for e in ESPECIES if e in set(cambio.especies))
        sub = df[df["comuna"].isin(p["comunas"])]
        if p["distritos"]:
            sub = sub[sub["distrito"].isin(p["distritos"])]
        if p["zona"]:
            en_zona = sub[sub["h3_index"].isin(p["zona"])]
            if len(en_zona):  # como en la app de Rol 3: una zona fuera del área no la vacía
                sub = en_zona
        if cambio.vecinas is not None:
            p["vecinas"] = cambio.vecinas
        # Apoyo: el resto de las comunas elegidas (si hay sector o zona) y sus comunas vecinas. Sus parques e islas
        # verdes sirven de extremo del corredor, que igual debe ir en su mayoría por lo elegido.
        apoyo = None
        if p.get("vecinas") and len(sub):
            cerca = set(p["comunas"]).union(*(vecinas[c] for c in p["comunas"]))
            apoyo = df[df["comuna"].isin(cerca) & ~df.index.isin(sub.index)]
        st["apoyo"] = apoyo if apoyo is not None and len(apoyo) else None
        anterior = st.get("area")
        st["p"], st["sub"] = p, sub
        st["area"] = tuple(sub.index)
        if st["area"] != anterior:
            estado["sel_seq"] += 1          # un contador para todas las sesiones: un sel_id nunca se repite
            st["sel_id"] = estado["sel_seq"]
        st["antes"] = resolver(st)
        st["vivo_visto"] = estado["live_mtime"]
        st["datos_visto"] = None
        st["cambios"] = st.get("cambios", 0) + 1

    def recalcular():
        """Llegó una captura o un video: el terreno cambia para todas las sesiones."""
        estado["terreno"] = alm.escribir_h3() if alm.capturas() or alm.escuchas() else None
        estado["datos"] += 1
        al_dia(estado)

    def al_dia(st: dict):
        """Recalcula el corredor de una sesión si cambiaron el terreno o la lectura en vivo desde su último cálculo."""
        if st.get("vivo_visto") != estado["live_mtime"]:
            st["antes"] = resolver(st)
            st["vivo_visto"] = estado["live_mtime"]
            st["datos_visto"] = None
        if st.get("datos_visto") != estado["datos"]:
            st["ahora"] = resolver(st, estado["terreno"])
            st["datos_visto"] = estado["datos"]

    def version(st: dict) -> int:
        return estado["datos"] * 1_000_000 + st["cambios"]

    def sesion(s: str | None) -> dict:
        """La sesión de un navegador (se crea con el área y los pesos por defecto); sin `s`, la compartida."""
        if not s:
            return estado
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", s):
            raise HTTPException(422, "Sesión inválida")
        st = sesiones.get(s)
        if st is None:
            st = {"p": {"comunas": list(inicial), "distritos": [], "zona": None, "km": km, "w": PESOS_INICIALES}}
            elegir(Seleccion(), st)
            sesiones[s] = st
            while len(sesiones) > MAX_SESIONES:
                sesiones.popitem(last=False)
        sesiones.move_to_end(s)
        al_dia(st)
        return st

    def refrescar_vivo():
        """Lanza un ciclo de vivo.py si live_h3.parquet está viejo; leer_live() lo toma en un próximo sondeo.
        Tras un intento espera refresco_s antes del siguiente, aunque haya fallado."""
        mt = ruta_live.stat().st_mtime if ruta_live.exists() else 0
        if not refresco_s or time.time() - max(mt, estado["intento_vivo"]) < refresco_s:
            return
        estado["intento_vivo"] = time.time()

        def correr():
            try:
                import vivo
                vivo.una_vez()
            except Exception as e:  # sin red o sin token: el mapa sigue con el último dato
                log.warning("Ciclo en vivo falló: %r", e)

        threading.Thread(target=correr, daemon=True).start()

    def revisar_live():
        refrescar_vivo()
        if leer_live():
            estado["datos"] += 1
            al_dia(estado)

    inicial = comunas or todas  # al abrir se ven todas; el mapa permite separar por comuna
    faltan = set(inicial) - set(todas)
    if faltan:
        raise ValueError(f"Comunas que no están en {datos}: {sorted(faltan)}")
    leer_live()
    elegir(Seleccion(comunas=inicial))
    al_dia(estado)
    app = FastAPI(title="VerdeH3")

    def revisar_clave(k: str | None):
        if clave and k != clave:
            raise HTTPException(403, "Clave incorrecta: abre la página con ?k=<clave>")

    sitio = web if web is not None and (Path(web) / "index.html").exists() else None

    @app.get("/")
    def inicio():
        """El sitio Viridis si está exportado; si no, el mapa."""
        return FileResponse(Path(sitio) / "index.html") if sitio else RedirectResponse("/mapa")

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
                    video: UploadFile | None = File(None), audio: UploadFile | None = File(None),
                    k: str | None = Query(None)):
        """Video grabado en la página: cuadros JPEG con su posición y hora, más el trazado GPS del recorrido.
        Si trae audio (WAV del micrófono mientras se caminaba), BirdNET lo escucha entero y cada ave queda en el
        hexágono donde iba el teléfono cuando cantó; cada tramo también mide el ruido de la calle."""
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

        paseo = None
        if audio is not None:
            wav = audio.file.read(MAX_AUDIO_PASEO + 1)
            try:
                if len(wav) > MAX_AUDIO_PASEO:
                    raise ValueError("audio de más de 24 MB")
                x, tasa = aves.leer_wav(wav)
            except ValueError as e:
                paseo = {"error": str(e)}
            else:
                t = hora(m.get("inicio"))
                fecha = pd.Timestamp(t).to_pydatetime().replace(tzinfo=None) if t else None
                p0 = track[0] if track else info[validos[0]]
                paseo = {"wav": wav, "dur": len(x) / tasa, "dbs": aves.ruido_por_segundo(x, tasa),
                         "crudas": aves.detectar_crudo(x, tasa, p0["lat"], p0["lon"], fecha),
                         "tramos": aves.tramos_por_hexagono(track, len(x) / tasa)}
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
            escuchas = []
            if paseo and "wav" in paseo:
                archivo = alm.guardar_wav(paseo["wav"], rec["id"])
                crudas = paseo["crudas"]
                for tr in paseo["tramos"]:
                    dets = None if crudas is None else aves.agrupar(
                        [d for d in crudas if tr["desde_s"] <= (d["inicio_s"] + d["fin_s"]) / 2 < tr["hasta_s"]])
                    dbs = paseo["dbs"][int(tr["desde_s"]):max(int(tr["desde_s"]) + 1, int(tr["hasta_s"]))]
                    cuando = pd.Timestamp(hora(m.get("inicio"))) + pd.Timedelta(seconds=tr["desde_s"]) if hora(m.get("inicio")) else None
                    escuchas.append(alm.guardar_audio(
                        None, tr["lat"], tr["lon"], tr["precision_m"], cuando.isoformat() if cuando is not None else None,
                        dets, tr["hasta_s"] - tr["desde_s"], aves.resumir_ruido(dbs), archivo,
                        extra={"video_id": rec["id"], "desde_s": tr["desde_s"], "hasta_s": tr["hasta_s"]}))
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
            "aves": None if paseo is None else {
                "error": paseo.get("error"), "analizada": bool(escuchas) and escuchas[0]["analizada"],
                "tramos": len(escuchas),
                "especies": aves.agrupar([d for e in escuchas for d in e["detecciones"]]),
                "ruido": aves.resumir_ruido(paseo.get("dbs", [])),
                "no_concluyentes": sum(not e["concluyente"] for e in escuchas)},
            "corredor_cambio": set(previo["hexes"]) != set(ahora["hexes"]),
            "antes": _resumen(estado["antes"]), "previo": _resumen(previo), "ahora": _resumen(ahora),
        }

    def es_local(request: Request) -> bool:
        """El mapa abierto en el mismo computador (no por el túnel, que agrega cf-connecting-ip)."""
        return (request.client is not None and request.client.host in ("127.0.0.1", "::1", "testclient")
                and "cf-connecting-ip" not in request.headers)

    def _parametros(st: dict) -> dict:
        p = st["p"]
        return {"comunas": p["comunas"], "distritos": p["distritos"], "zona": len(p["zona"] or []),
                "km": p["km"], "w_calor": p["w"][0], "w_arbol": p["w"][1], "w_personas": p["w"][2],
                "w_bio": p["w"][3], "w_vuln": p["w"][4], "vecinas": bool(p.get("vecinas")), "especies": list(p.get("especies") or ("humanos",)),
                "perfil": PERFIL_DE.get(frozenset(p.get("especies") or ("humanos",)), "mixto"), "birdnet": aves.estado()}

    dist_por_comuna = {c: sorted(v, key=lambda n: int(n.rsplit(" ", 1)[1])) for c, v in distritos_de.items()}

    def _fauna(hexes: list[str], terreno) -> dict:
        """Especies de aves y polinizadores registrados en terreno dentro de un corredor."""
        if terreno is None or not len(terreno):
            return {"especies": [], "polinizadores": 0}
        t = terreno[terreno["h3_index"].isin(set(hexes))]
        especies = sorted({e for x in t["especies_aves"] for e in x.split("; ") if e})
        return {"especies": especies, "polinizadores": int(t["n_polinizadores"].sum())}

    @app.post("/api/audio")
    def subir_audio(audio: UploadFile = File(...), lat: float = Form(...), lon: float = Form(...),
                    precision_m: float | None = Form(None), tomado_en: str | None = Form(None),
                    k: str | None = Query(None)):
        """Escucha de aves: WAV de la página del teléfono, con su posición y hora. BirdNET identifica especies."""
        revisar_clave(k)
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise HTTPException(422, "Coordenadas fuera de rango")
        wav = audio.file.read(MAX_AUDIO_BYTES + 1)
        if len(wav) > MAX_AUDIO_BYTES:
            raise HTTPException(413, "Audio de más de 6 MB")
        try:
            x, tasa = aves.leer_wav(wav)
        except ValueError as e:
            raise HTTPException(422, str(e))
        t = hora(tomado_en)
        detecciones = aves.detectar(wav, lat, lon, pd.Timestamp(t).to_pydatetime().replace(tzinfo=None) if t else None)
        ruido = aves.resumir_ruido(aves.ruido_por_segundo(x, tasa))
        with lock:
            previo = estado["ahora"]
            esc = alm.guardar_audio(wav, lat, lon, precision_m, tomado_en, detecciones, len(x) / tasa, ruido)
            recalcular()
            ahora = estado["ahora"]
        return {
            "escucha": esc, "analizada": detecciones is not None,
            "fuera_de_area": esc["h3_index"] not in hex_area, "comuna": comuna_de.get(esc["h3_index"]),
            "fuera_de_seleccion": esc["h3_index"] not in set(estado["sub"]["h3_index"]),
            "en_corredor": esc["h3_index"] in ahora["hexes"],
            "corredor_cambio": set(previo["hexes"]) != set(ahora["hexes"]),
            "antes": _resumen(estado["antes"]), "previo": _resumen(previo), "ahora": _resumen(ahora),
        }

    @app.get("/audios/{nombre}")
    def audios(nombre: str):
        if not AUDIO_OK.match(nombre) or not (alm.audios / nombre).exists():
            raise HTTPException(404)
        return FileResponse(alm.audios / nombre, media_type="audio/wav")

    @app.get("/api/salud")
    def salud():
        return {"ok": True}

    @app.get("/api/comunas")
    def api_comunas(s: str | None = Query(None)):
        with lock:
            st = sesion(s)
            return {"comunas": todas, "vecinas": vecinas, "geo": geo, "distritos": dist_por_comuna,
                    "seleccion": st["p"]["comunas"], "parametros": _parametros(st)}

    @app.post("/api/seleccion")
    def api_seleccion(request: Request, cambio: Seleccion, k: str | None = Query(None), s: str | None = Query(None)):
        """Cambia área, presupuesto o pesos. Con `s` solo cambia la sesión de ese navegador y no pide clave; la
        sesión compartida (sin `s`) no pide clave desde el mismo computador, pero por el túnel sí."""
        if not s and not es_local(request):
            revisar_clave(k)
        with lock:
            st = sesion(s)
            elegir(cambio, st)
            al_dia(st)
            return {"seleccion": st["p"]["comunas"], "parametros": _parametros(st),
                    "antes": _resumen(st["antes"]), "ahora": _resumen(st["ahora"])}

    @app.get("/api/version")
    def api_version(s: str | None = Query(None)):
        """Sondeo barato del mapa: cambia con cada captura, video, selección o lectura en vivo nueva."""
        with lock:
            revisar_live()
            st = sesion(s)
            return {"version": version(st), "sel_id": st["sel_id"]}

    @app.get("/api/estado")
    def api_estado(sel_id: int | None = Query(None), s: str | None = Query(None)):
        """Hexágonos del área en columnas. Los polígonos solo van si el mapa no tiene los de esta área (sel_id)."""
        with lock:
            revisar_live()
            st = sesion(s)
            ahora, antes, sub = (st[x] for x in ("ahora", "antes", "sub"))
            terreno, live = estado["terreno"], estado["live"]
            ver, sid, params = version(st), st["sel_id"], _parametros(st)
            caps = alm.capturas()
            escuchas = alm.escuchas()
        # El mapa recibe solo cuántas fotos y escuchas hay por hexágono; el detalle se pide al tocarlo
        # (/api/hexagono/{h}), para que miles de capturas no viajen en cada sondeo ni llenen el mapa de puntos.
        n_fotos = Counter(c["h3_index"] for c in caps if cuenta(c, aceptar_sin_validar))
        n_escuchas = Counter(e["h3_index"] for e in escuchas if e.get("analizada"))
        verif = set(terreno.loc[terreno["n_capturas"] > 0, "h3_index"]) if terreno is not None else set()
        t_idx = terreno.set_index("h3_index") if terreno is not None and len(terreno) else None
        bio = sub["h3_index"].map(t_idx["biodiversidad_terreno"]) if t_idx is not None else pd.Series(float("nan"), index=sub.index)
        especies = sub["h3_index"].map(t_idx["especies_aves"]).fillna("") if t_idx is not None else pd.Series("", index=sub.index)
        poli = sub["h3_index"].map(t_idx["n_polinizadores"]).fillna(0) if t_idx is not None else pd.Series(0, index=sub.index)
        en_antes, en_ahora = set(antes["hexes"]), set(ahora["hexes"])
        en_cp = set(ahora.get("checkpoints", []))
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
            "vuln": [_r(x, 3) for x in sub["vulnerabilidad"]] if "vulnerabilidad" in sub else [None] * len(hs),
            "parque": sub["es_parque"].astype(bool).tolist(),
            "antes": [h in en_antes for h in hs], "ahora": [h in en_ahora for h in hs],
            "checkpoint": [h in en_cp for h in hs],
            "verificado": [h in verif for h in hs],
            "bio": [_r(x, 3) for x in bio], "especies": especies.tolist(), "polinizadores": poli.astype(int).tolist(),
            "fotos": [n_fotos.get(h, 0) for h in hs], "escuchas": [n_escuchas.get(h, 0) for h in hs],
        }
        if sel_id != sid:
            col["pol"] = [poligonos[h] for h in hs]
        recorridos = [{"id": r["id"], "inicio": r.get("inicio"), "duracion_s": r.get("duracion_s"),
                       "archivo": r.get("archivo"), "linea": [[p["lat"], p["lon"]] for p in r.get("track", [])]}
                      for r in alm.recorridos()]
        # Última lectura de aire que entra al mapa (confianza alta o media); None si no hay.
        vivo_fecha = None
        if live is not None and len(live) and "medido_en" in live:
            ok_v = live[live["confianza"].isin(["alta", "media"]) & live["temp_aire_c"].notna()]["medido_en"].dropna()
            vivo_fecha = str(ok_v.max()) if len(ok_v) else None
        return {"version": ver, "sel_id": sid, "seleccion": params["comunas"], "parametros": params, "lst_fecha": lst_fecha,
                "fechas": {"calor": lst_fecha, "copa": copa_fecha, "vivo": vivo_fecha},
                "hex": col, "recorridos": recorridos, "en_vivo": live is not None,
                "totales": {"capturas": len(caps), "cuentan": sum(n_fotos.values()),
                            "escuchas": sum(n_escuchas.values())},
                "fauna_corredor": _fauna(ahora["hexes"], terreno),
                # Cuadras del corredor en comunas vecinas (opción «vecinas»): no están en `hex`, van aparte.
                "fuera": [{"h": h, "comuna": comuna_de.get(h), "isla": h in en_cp} for h in ahora.get("fuera", [])],
                "antes": {**_resumen(antes), "personas_azar": antes["personas_azar"]},
                "ahora": {**_resumen(ahora), "personas_azar": ahora["personas_azar"]}}

    @app.get("/api/hexagono/{h}")
    def api_hexagono(h: str, n: int = Query(12, ge=1, le=60)):
        """Lo registrado en terreno en un hexágono, lo más nuevo primero: fotos que cuentan (las descartadas y sin
        validar no se muestran), escuchas de aves analizadas y el resumen de fauna. Hasta n fotos y 5 escuchas."""
        if h not in hex_area and not re.fullmatch(r"[0-9a-f]{15}", h):
            raise HTTPException(404)
        with lock:
            terreno = estado["terreno"]
            fotos = sorted((c for c in alm.capturas() if c["h3_index"] == h and cuenta(c, aceptar_sin_validar)),
                           key=lambda c: c["medido_en"], reverse=True)
            escs = sorted((e for e in alm.escuchas() if e["h3_index"] == h and e.get("analizada")),
                          key=lambda e: e["medido_en"], reverse=True)
        fila = {}
        if terreno is not None and h in set(terreno["h3_index"]):
            r = terreno.set_index("h3_index").loc[h]
            fila = {"especies": [e for e in str(r["especies_aves"]).split("; ") if e],
                    "polinizadores": int(r["n_polinizadores"]),
                    "flores": None if pd.isna(r["flores"]) else float(r["flores"]),
                    "biodiversidad": float(r["biodiversidad_terreno"]),
                    "viabilidad": None if pd.isna(r["viabilidad_terreno"]) else float(r["viabilidad_terreno"])}
        claves = ("id", "medido_en", "tomado_en", "arbol_pct", "espacio_plantable", "obstaculos", "fauna", "flores",
                  "tipo_foto", "descripcion", "fuente", "precision_m", "video_id")
        return {"h3_index": h, "comuna": comuna_de.get(h), "n_fotos": len(fotos), "n_escuchas": len(escs),
                "fotos": [{k2: c.get(k2) for k2 in claves} for c in fotos[:n]], "escuchas": escs[:5], **fila}

    @app.get("/api/capturas")
    def api_capturas():
        """Todas las capturas y escuchas con su estado de validación (para revisar o exportar; el mapa no lo usa)."""
        with lock:
            caps = [{**c, "validacion": estado_validacion(c), "cuenta": cuenta(c, aceptar_sin_validar)}
                    for c in alm.capturas()]
            return {"capturas": caps, "escuchas": alm.escuchas()}

    @app.get("/api/historico")
    def api_historico(desde: str = Query(...), hasta: str = Query(...), s: str | None = Query(None)):
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
            hs = set(sesion(s)["sub"]["h3_index"])
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

    if sitio:  # al final: las rutas de arriba (API, fotos, audios, /captura, /mapa) tienen prioridad
        app.mount("/", StaticFiles(directory=sitio, html=True), name="sitio")
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
    aves.precargar()  # el modelo de BirdNET tarda unos segundos: que la primera escucha no espere
    import uvicorn
    uvicorn.run(crear_app(a.datos, a.data, a.km, a.clave, not a.sin_claude, a.aceptar_sin_validar, a.comunas), host=a.host, port=a.puerto)


if __name__ == "__main__":
    main()
