"""Servidor de captura en terreno: el teléfono sube fotos con GPS, el corredor se recalcula y el mapa se actualiza.

    python -m terreno.servidor --datos data/santiago_h3.parquet --puerto 8000
    cloudflared tunnel --url http://localhost:8000      # HTTPS público: el GPS del teléfono lo exige

Teléfono: https://<túnel>/?k=<clave>   ·   Mapa para proyectar: http://localhost:8000/mapa
Si TERRENO_CLAVE (o --clave) está definida, subir fotos exige ?k=<clave>, porque la URL del túnel es pública.
Solo cuentan las fotos que Claude valida como exteriores de calle; sin Claude quedan «sin validar» y no cambian
el corredor, salvo con --aceptar-sin-validar (demo sin red).
Credenciales de Claude: ANTHROPIC_API_KEY, un perfil de `ant auth login`, o la clave sola en el archivo
.anthropic_key en la raíz del repo (está en .gitignore; nunca la subas).
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import threading
from pathlib import Path

import h3
import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from optimizer import solve_corridor
from terreno.almacen import Almacen, cuenta, estado_validacion
from terreno.vision import analizar

ESTATICO = Path(__file__).resolve().parent / "static"
MAX_FOTO_BYTES = 15 * 1024 * 1024
FOTO_OK = re.compile(r"^[0-9T]{15}-[0-9a-f]{6}(_min)?\.jpg$")
log = logging.getLogger("terreno")


def _resumen(r: dict) -> dict:
    return {"hexes": len(r["hexes"]), "km": round(r["length_km"], 2),
            "urgencia_cubierta": round(r["urgencia_cubierta"], 3), "urgencia_azar": round(r["urgencia_azar"], 3),
            "personas_cubiertas": r["personas_cubiertas"], "verificados": r.get("verificados", 0)}


def crear_app(datos: Path = Path("data/santiago_h3.parquet"), data_dir: Path = Path("data"),
              km: float = 3.0, clave: str | None = None, usar_claude: bool = True,
              aceptar_sin_validar: bool = False) -> FastAPI:
    df = pd.read_parquet(datos)
    alm = Almacen(data_dir, aceptar_sin_validar)
    antes = solve_corridor(df, km)
    hex_area = set(df["h3_index"])
    poligonos = {h: [[round(la, 6), round(lo, 6)] for la, lo in h3.cell_to_boundary(h)] for h in df["h3_index"]}
    lock = threading.Lock()
    estado: dict = {}

    def recalcular():
        terreno = alm.escribir_h3() if alm.capturas() else None
        estado["terreno"] = terreno
        estado["ahora"] = solve_corridor(df, km, terreno=terreno)

    recalcular()
    app = FastAPI(title="VerdeH3 · captura en terreno")

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
                nota: str = Form(""), k: str | None = Query(None)):
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
            cap = alm.guardar(datos_foto, lat, lon, precision_m, rumbo, nota, obs)
            recalcular()
            ahora = estado["ahora"]
        return {
            "captura": cap,
            "validacion": estado_validacion(cap),
            "cuenta": cuenta(cap, aceptar_sin_validar),
            "fuera_de_area": cap["h3_index"] not in hex_area,
            "en_corredor": cap["h3_index"] in ahora["hexes"],
            "corredor_cambio": set(previo["hexes"]) != set(ahora["hexes"]),
            "antes": _resumen(antes), "previo": _resumen(previo), "ahora": _resumen(ahora),
        }

    @app.get("/api/estado")
    def api_estado():
        with lock:
            ahora, terreno = estado["ahora"], estado["terreno"]
            caps = [{**c, "validacion": estado_validacion(c), "cuenta": cuenta(c, aceptar_sin_validar)}
                    for c in alm.capturas()]
        verif = set(terreno["h3_index"]) if terreno is not None else set()
        en_antes, en_ahora = set(antes["hexes"]), set(ahora["hexes"])
        U = ahora["urgencia"]
        hexes = [{"h": h, "pol": poligonos[h], "u": round(float(u), 3), "parque": bool(p),
                  "antes": h in en_antes, "ahora": h in en_ahora, "verificado": h in verif}
                 for h, u, p in zip(df["h3_index"], U, df["es_parque"])]
        return {"hexes": hexes, "capturas": caps, "antes": _resumen(antes), "ahora": _resumen(ahora)}

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
    p.add_argument("--datos", type=Path, default=Path("data/santiago_h3.parquet"))
    p.add_argument("--data", type=Path, default=Path("data"), help="dónde guardar capturas y terreno_h3.parquet")
    p.add_argument("--km", type=float, default=3.0)
    p.add_argument("--puerto", type=int, default=8000)
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
    uvicorn.run(crear_app(a.datos, a.data, a.km, a.clave, not a.sin_claude, a.aceptar_sin_validar), host=a.host, port=a.puerto)


if __name__ == "__main__":
    main()
