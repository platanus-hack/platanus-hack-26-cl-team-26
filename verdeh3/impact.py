"""% de árboles por hexágono con el mapa anual de cobertura de Impact Observatory y Esri (10 m).

python -m verdeh3.impact                 # año más reciente y 2021 -> arbol_pct_io_<año>
python -m verdeh3.impact --anios 2023

Colección io-lulc-annual-v02 de Planetary Computer (Sentinel-2, 9 clases; clase 2 = árboles).
Ref.: Karra et al. (2021), "Global land use/land cover with Sentinel 2 and deep learning", IGARSS.
Columnas aparte: no cambia arbol_pct (WorldCover 2021) ni la fórmula del índice.
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from . import fuentes, grilla
from .worldcover import _bloques

log = logging.getLogger("verdeh3")

COLECCION = "io-lulc-annual-v02"
CLASE_ARBOLES = 2
DECIMACION = 2


def items_por_anio(bbox) -> dict[int, object]:
    its = fuentes._stac().search(collections=[COLECCION], bbox=bbox).items()
    return {int(i.properties["start_datetime"][:4]): i for i in its}


def clases(it, bbox, cache: Path):
    ruta = cache / f"io_lulc_{it.id}.tif"
    if not ruta.exists():
        arr, t, crs = fuentes._leer_recorte(it.assets["data"].href, bbox, 1, "nearest")
        arr = arr.astype("float32")
        arr[arr == 0] = np.nan
        fuentes._guardar_tif(ruta, arr, t, crs, {"fuente": it.id})
    return fuentes._leer_tif(ruta)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--anios", default="", help="separados por comas; vacío = el más reciente y 2021")
    p.add_argument("--salida", type=Path, default=Path("datos/salida_h3_gs"))
    p.add_argument("--cache", type=Path, default=Path("datos/cache_gs"))
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    ruta = a.salida / "santiago_h3.parquet"
    tabla = gpd.read_parquet(ruta)
    bbox = tuple(round(v, 5) for v in tabla.total_bounds)
    disponibles = items_por_anio(bbox)
    anios = [int(x) for x in a.anios.split(",") if x] or sorted({max(disponibles), 2021})
    log.info("Años disponibles: %s; uso %s", sorted(disponibles), anios)

    hexs = {r: g.copy() for r, g in tabla.groupby("res")}
    for anio in anios:
        arr, t, crs, _ = clases(disponibles[anio], bbox, a.cache)
        ind = np.where(np.isfinite(arr), (arr == CLASE_ARBOLES).astype("float32"), np.nan)
        col = f"arbol_pct_io_{anio}"
        grilla.agregar_raster(hexs, 100 * _bloques(ind, DECIMACION), t * t.scale(DECIMACION, DECIMACION), crs, col)
        for r, h in hexs.items():
            log.info("res %d: %s medio %.1f%%, %d sin dato", r, col, h[col].mean(), h[col].isna().sum())
    tabla = gpd.GeoDataFrame(pd.concat(hexs.values()).sort_index(), crs=tabla.crs)
    geom = tabla.pop("geometry")
    gpd.GeoDataFrame(tabla.assign(geometry=geom), crs=geom.crs).to_parquet(ruta, index=False)


if __name__ == "__main__":
    main()
