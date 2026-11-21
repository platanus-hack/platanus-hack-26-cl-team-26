"""Ciclo en vivo: cada 5 minutos lee los sensores, filtra, interpola por barrio y escribe los archivos.

Uso:
  python vivo.py                    # en vivo, graba el crudo en data/grabacion/AAAA-MM-DD.csv
  MODO=reproducir python vivo.py    # rehace los ciclos grabados con su hora original
  UNA_VEZ=1 python vivo.py          # un solo ciclo

El servidor (terreno/servidor.py) llama a una_vez() cuando alguien mira el mapa y live_h3.parquet tiene más
de REFRESCO_VIVO_MIN minutos: así hay datos en vivo en Render sin dejar este ciclo corriendo.
"""
import json
import os
import time
from pathlib import Path

import h3
import pandas as pd

import calidad
import fuentes
import interpolar

DATA = Path("data")
GRAB = DATA / "grabacion"
PERIODO_S = 300


def escribir(ruta, escribir_tmp):
    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    escribir_tmp(tmp)
    os.replace(tmp, ruta)


def grabar(crudo, leido_en):
    GRAB.mkdir(parents=True, exist_ok=True)
    ruta = GRAB / f"{leido_en.tz_convert(fuentes.TZ):%Y-%m-%d}.csv"
    crudo.assign(leido_en=leido_en).to_csv(ruta, mode="a", header=not ruta.exists(), index=False)


def alerta(live, antes):
    """10 % más caluroso de los barrios con dato; quien ya estaba en alerta sigue hasta bajar del 20 %."""
    pct = live.temp_aire_c.rank(pct=True)
    return (pct > 0.9) | (live.h3_padre.isin(antes) & (pct > 0.8))


def ciclo(crudo, ahora, b, previo, errores, antes=()):
    buenas, descartes = calidad.filtrar(crudo, ahora, previo)
    live = interpolar.por_barrio(buenas, b)
    live["alerta"] = alerta(live, antes)
    escribir(DATA / "live_h3.parquet", lambda p: live.to_parquet(p, index=False))
    web = buenas.assign(h3_padre=[h3.latlng_to_cell(a, o, interpolar.RES_BARRIO) for a, o in zip(buenas.lat, buenas.lon)],
                        medido_en=buenas.medido_en.map(lambda t: t.isoformat()))
    cols = ["source", "lat", "lon", "h3_padre", "temp_c", "humedad_pct", "medido_en", "oficial"]
    registros = json.loads(web[cols].to_json(orient="records"))
    escribir(DATA / "web_sensors.json", lambda p: p.write_text(json.dumps(registros, ensure_ascii=False)))
    estado = {"ciclo": ahora.isoformat(), "lecturas": len(crudo), "aceptadas": len(buenas),
              "descartes": descartes, "errores_fuentes": errores,
              "confianza": live.confianza.value_counts().to_dict()}
    escribir(DATA / "vivo_estado.json", lambda p: p.write_text(json.dumps(estado, ensure_ascii=False, indent=1)))
    print(json.dumps(estado, ensure_ascii=False))
    return buenas, set(live.h3_padre[live.alerta])


def leer_grabacion():
    partes = [pd.read_csv(p) for p in sorted(GRAB.glob("*.csv"))]
    g = pd.concat(partes, ignore_index=True)
    for c in ("medido_en", "leido_en"):
        g[c] = pd.to_datetime(g[c], utc=True, format="ISO8601")
    return g


def una_vez():
    """Un ciclo en vivo con la hora actual: lee, graba, filtra, interpola y escribe los archivos."""
    ahora = pd.Timestamp.now(tz="UTC")
    crudo, errores = fuentes.leer_todo()
    if not len(crudo):
        print(f"{ahora}: ninguna fuente respondió {errores}")
        return
    grabar(crudo, ahora)
    ciclo(crudo, ahora, interpolar.barrios(pd.read_parquet(DATA / "santiago_h3.parquet")), None, errores)


def main():
    b = interpolar.barrios(pd.read_parquet(DATA / "santiago_h3.parquet"))
    previo, antes = None, set()
    if os.getenv("MODO") == "reproducir":
        for leido_en, crudo in leer_grabacion().groupby("leido_en"):
            previo, antes = ciclo(crudo.drop(columns="leido_en").reset_index(drop=True), leido_en, b, previo, {}, antes)
            time.sleep(float(os.getenv("PAUSA_S", "0")))
        return
    while True:
        inicio = time.time()
        try:
            ahora = pd.Timestamp.now(tz="UTC")
            crudo, errores = fuentes.leer_todo()
            if len(crudo):
                grabar(crudo, ahora)
                previo, antes = ciclo(crudo, ahora, b, previo, errores, antes)
            else:
                print(f"{ahora}: ninguna fuente respondió {errores}")
        except Exception as e:  # nunca se cae: registra y espera el próximo ciclo
            print(f"error en el ciclo: {e!r}")
        if os.getenv("UNA_VEZ"):
            return
        time.sleep(max(0, PERIODO_S - (time.time() - inicio)))


if __name__ == "__main__":
    main()
