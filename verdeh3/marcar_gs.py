"""Columnas para filtrar la corrida del Gran Santiago, sin recalcular el pipeline.

python -m verdeh3.marcar_gs --salida salida_h3_gs --cache cache_gs

Agrega a santiago_h3.parquet:
  comuna_piloto    True en las 4 comunas de la primera corrida (config.COMUNAS_PILOTO)
  elev_m           altura media del hexágono (Copernicus DEM 30 m)
  precordillera    elev_m >= COTA_PRECORDILLERA_M
  baja_poblacion   densidad < DENSIDAD_MIN_HAB_KM2 (incluye parques e industrias, no solo cerro)
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd

from . import config, fuentes, grilla

log = logging.getLogger("verdeh3")

COTA_PRECORDILLERA_M = 900
DENSIDAD_MIN_HAB_KM2 = 500


def elevacion_dem(bbox, cache: Path):
    """Copernicus DEM GLO-30 recortado al bbox (cache/elev_cop30.tif)."""
    import numpy as np
    from rasterio.merge import merge
    import rasterio

    ruta = cache / "elev_cop30.tif"
    if not ruta.exists():
        its = list(fuentes._stac().search(collections=["cop-dem-glo-30"], bbox=bbox).items())
        srcs = [rasterio.open(i.assets["data"].href) for i in its]
        try:
            arr, t = merge(srcs, bounds=bbox)
            crs = srcs[0].crs
        finally:
            for s in srcs:
                s.close()
        arr = arr[0].astype("float64")
        arr[arr < -100] = np.nan
        fuentes._guardar_tif(ruta, arr, t, crs, {"fuente": ",".join(i.id for i in its)})
    return fuentes._leer_tif(ruta)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--salida", type=Path, default=Path("salida_h3_gs"))
    p.add_argument("--cache", type=Path, default=Path("cache_gs"))
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    ruta = a.salida / "santiago_h3.parquet"
    tabla = gpd.read_parquet(ruta)
    bbox = tuple(round(v, 5) for v in tabla.total_bounds)

    hexs = {r: g.copy() for r, g in tabla.groupby("res")}
    grilla.agregar_raster(hexs, *elevacion_dem(bbox, a.cache)[:3], "elev_m")
    tabla = gpd.GeoDataFrame(pd.concat(hexs.values()).sort_index(), crs=tabla.crs)
    tabla["elev_m"] = tabla["elev_m"].round(0)
    tabla["comuna_piloto"] = tabla["comuna"].isin(config.COMUNAS_PILOTO)
    tabla["precordillera"] = tabla["elev_m"] >= COTA_PRECORDILLERA_M
    tabla["baja_poblacion"] = tabla["densidad_hab_km2"] < DENSIDAD_MIN_HAB_KM2
    geom = tabla.pop("geometry")
    tabla = gpd.GeoDataFrame(tabla.assign(geometry=geom), crs=geom.crs)
    tabla.to_parquet(ruta, index=False)
    for r, g in tabla.groupby("res"):
        log.info("res %d: %d hex, %d precordillera, %d baja población, %d en comunas piloto",
                 r, len(g), g["precordillera"].sum(), g["baja_poblacion"].sum(), g["comuna_piloto"].sum())


if __name__ == "__main__":
    main()
