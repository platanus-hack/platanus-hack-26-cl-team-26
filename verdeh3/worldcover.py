"""Árboles contra pasto por hexágono con ESA WorldCover 2021 v200 (10 m, Planetary Computer).

python -m verdeh3.worldcover --salida datos/salida_h3_gs --cache datos/cache_gs

Agrega a santiago_h3.parquet (fracción 0 a 1 del hexágono, sobre los píxeles con dato):
  frac_arboles   clase 10 "Tree cover"
  frac_pasto     clase 30 "Grassland"
  frac_arbustos  clase 20 "Shrubland"
  frac_construido clase 50 "Built-up"

NDVI no separa un prado regado de un árbol; WorldCover sí. El pasto no da sombra.
Ref.: Zanaga et al. (2022), ESA WorldCover 10 m 2021 v200, doi:10.5281/zenodo.7254221.
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from . import fuentes, grilla

log = logging.getLogger("verdeh3")

ITEM = "ESA_WorldCover_10m_2021_v200"
CLASES = {"arboles": 10, "arbustos": 20, "pasto": 30, "construido": 50}
DECIMACION = 2  # fracciones promediadas en bloques de 2x2 píxeles (20 m)


def clases_worldcover(bbox, cache: Path):
    """Ráster de clases recortado al bbox (cache/worldcover_2021.tif, uint8 guardado como float)."""
    ruta = cache / "worldcover_2021.tif"
    if not ruta.exists():
        from rasterio.merge import merge
        import rasterio

        its = [i for i in fuentes._stac().search(collections=["esa-worldcover"], bbox=bbox).items()
               if i.id.startswith(ITEM)]
        if not its:
            raise RuntimeError(f"Sin teselas {ITEM} para {bbox}")
        srcs = [rasterio.open(i.assets["map"].href) for i in its]
        try:
            arr, t = merge(srcs, bounds=bbox)
            crs = srcs[0].crs
        finally:
            for s in srcs:
                s.close()
        arr = arr[0].astype("float32")
        arr[arr == 0] = np.nan
        fuentes._guardar_tif(ruta, arr, t, crs, {"fuente": ",".join(i.id for i in its)})
    return fuentes._leer_tif(ruta)


def _bloques(x: np.ndarray, d: int) -> np.ndarray:
    """Promedio en bloques d x d ignorando NaN."""
    h, w = (x.shape[0] // d) * d, (x.shape[1] // d) * d
    b = x[:h, :w].reshape(h // d, d, w // d, d)
    with np.errstate(invalid="ignore"):
        return np.nanmean(b, axis=(1, 3))


def agregar_worldcover(hexs: dict[int, gpd.GeoDataFrame], bbox, cache: Path) -> None:
    arr, t, crs, _ = clases_worldcover(bbox, cache)
    t_dec = t * t.scale(DECIMACION, DECIMACION)
    for nombre, clase in CLASES.items():
        ind = np.where(np.isfinite(arr), (arr == clase).astype("float32"), np.nan)
        grilla.agregar_raster(hexs, _bloques(ind, DECIMACION), t_dec, crs, f"frac_{nombre}")
        log.info("WorldCover %s listo", nombre)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--salida", type=Path, default=Path("datos/salida_h3_gs"))
    p.add_argument("--cache", type=Path, default=Path("datos/cache_gs"))
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    ruta = a.salida / "santiago_h3.parquet"
    tabla = gpd.read_parquet(ruta)
    bbox = tuple(round(v, 5) for v in tabla.total_bounds)

    hexs = {r: g.copy() for r, g in tabla.groupby("res")}
    agregar_worldcover(hexs, bbox, a.cache)
    tabla = gpd.GeoDataFrame(pd.concat(hexs.values()).sort_index(), crs=tabla.crs)
    geom = tabla.pop("geometry")
    tabla = gpd.GeoDataFrame(tabla.assign(geometry=geom), crs=geom.crs)
    tabla.to_parquet(ruta, index=False)
    for r, g in tabla.groupby("res"):
        log.info("res %d: árboles %.1f%%, pasto %.1f%%, construido %.1f%%, sin dato %d hex", r,
                 100 * g["frac_arboles"].mean(), 100 * g["frac_pasto"].mean(),
                 100 * g["frac_construido"].mean(), g["frac_arboles"].isna().sum())


if __name__ == "__main__":
    main()
