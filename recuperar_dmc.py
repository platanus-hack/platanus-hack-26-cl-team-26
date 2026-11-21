"""Recupera datos pasados de las estaciones DMC de Santiago, para tapar huecos de la grabación.

Uso:
  python recuperar_dmc.py              # últimas 12 h, minuto a minuto
  python recuperar_dmc.py 2026 11      # mes completo

Escribe data/grabacion_dmc/<nombre>.csv con las columnas de fuentes.COLUMNAS. Va en otra carpeta que
data/grabacion/ para que MODO=reproducir de vivo.py no lo mezcle con los ciclos grabados.
Se puede correr varias veces: reescribe el archivo. No escribe nada si la DMC no responde.
"""
import sys
from pathlib import Path

import pandas as pd

import fuentes

SALIDA = Path("data/grabacion_dmc")


def main(args):
    codigos = sorted(s.removeprefix("DMC_") for s in fuentes.dmc_estaciones().source.unique())
    if len(args) == 2:
        anio, mes = int(args[0]), int(args[1])
        partes, nombre = [fuentes.dmc_mes(c, anio, mes) for c in codigos], f"{anio}-{mes:02d}.csv"
    else:
        partes = [fuentes.dmc_12h(c) for c in codigos]
        nombre = f"{pd.Timestamp.now(tz=fuentes.TZ):%Y-%m-%d}_12h.csv"
    df = pd.concat([p for p in partes if len(p)], ignore_index=True) if any(len(p) for p in partes) else None
    if df is None:
        print("La DMC no trajo lecturas: no se escribe nada")
        return
    SALIDA.mkdir(parents=True, exist_ok=True)
    df.sort_values(["source", "medido_en"]).to_csv(SALIDA / nombre, index=False)
    desde = df.medido_en.min().tz_convert(fuentes.TZ)
    print(f"{len(df)} lecturas de {df.source.nunique()} estaciones desde {desde:%Y-%m-%d %H:%M} → {SALIDA / nombre}")


if __name__ == "__main__":
    main(sys.argv[1:])
