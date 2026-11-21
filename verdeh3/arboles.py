"""Árboles por hexágono desde el mapa de altura de copa de Meta y WRI (1 m, imágenes Maxar 2019).

python -m verdeh3.arboles --comunas "Providencia,Cerro Navia"

Fuente: Tolan et al. (2024), "Very high resolution canopy height maps from RGB imagery using
self-supervised vision transformer and convolutional decoder trained on aerial lidar", Remote Sensing of
Environment 300. s3://dataforgood-fb-data/forests/v1/alsgedi_global_v6_float/ (tesela 210231031 cubre
el Gran Santiago; imágenes de origen de oct-nov 2019). Baja la tesela a cache/meta_chm/ (332 MB).

Agrega a santiago_h3.parquet (res 9, solo las comunas pedidas):
  copa_pct      % del hexágono con vegetación de 3 m o más
  altura_copa_m altura media de esa vegetación
  n_arboles     árboles estimados: máximos locales de la copa suavizada, >= 3 m y separados >= 4 m
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from rasterio.windows import from_bounds
from scipy import ndimage

from . import fuentes

log = logging.getLogger("verdeh3")

URL = "https://dataforgood-fb-data.s3.amazonaws.com/forests/v1/alsgedi_global_v6_float/chm/210231031.tif"
ALTURA_MIN_M = 3
VENTANA_PX = 5  # ~4,8 m (píxel de 1,19 m en Mercator, ~1 m en el suelo a 33° S)


def por_hexagono(hex9: gpd.GeoDataFrame, chm: Path) -> pd.DataFrame:
    with rasterio.open(chm) as src:
        h = hex9.to_crs(src.crs)
        win = from_bounds(*h.total_bounds, transform=src.transform).round_offsets().round_lengths()
        alt = src.read(1, window=win).astype("float32")
        t = src.window_transform(win)
    ids = rasterize(zip(h.geometry, range(1, len(h) + 1)), out_shape=alt.shape, transform=t, fill=0,
                    dtype="int32")
    suave = ndimage.uniform_filter(alt, 3)
    pico = (suave == ndimage.maximum_filter(suave, VENTANA_PX)) & (suave >= ALTURA_MIN_M)
    copa = alt >= ALTURA_MIN_M
    df = pd.DataFrame({"id": ids.ravel(), "copa": copa.ravel(), "alt": np.where(copa, alt, np.nan).ravel(),
                       "pico": pico.ravel()})
    g = df[df["id"] > 0].groupby("id")
    out = pd.DataFrame({"copa_pct": 100 * g["copa"].mean(), "altura_copa_m": g["alt"].mean(),
                        "n_arboles": g["pico"].sum()})
    out.index = hex9["h3"].to_numpy()[out.index - 1]
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--comunas", default="Providencia,Cerro Navia")
    p.add_argument("--salida", type=Path, default=Path("datos/salida_h3_gs"))
    p.add_argument("--chm", type=Path, default=Path("cache/meta_chm/chm_210231031.tif"))
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    fuentes.descargar(URL, a.chm) if not a.chm.exists() else None
    ruta = a.salida / "santiago_h3.parquet"
    tabla = gpd.read_parquet(ruta)
    comunas = [c.strip() for c in a.comunas.split(",")]
    res = []
    for c in comunas:
        r = por_hexagono(tabla[(tabla["res"] == 9) & (tabla["comuna"] == c)], a.chm)
        log.info("%s: %d árboles, copa %.1f%%", c, r["n_arboles"].sum(), r["copa_pct"].mean())
        res.append(r)
    r = pd.concat(res)
    for col in r:
        tabla[col] = tabla["h3"].map(r[col]).combine_first(tabla[col]) if col in tabla else tabla["h3"].map(r[col])
    tabla.to_parquet(ruta, index=False)


if __name__ == "__main__":
    main()
