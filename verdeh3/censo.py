"""Población del Censo 2024 (INE) por hexágono, repartida desde las manzanas por área.

python -m verdeh3.censo --salida datos/salida_h3_gs --manzanas cache/censo2024/Cartografia_censo2024_Pais_Manzanas.parquet

La capa sale del zip "Cartografía País Censo 2024 (geoparquet)" de censo2024.ine.gob.cl (no se versiona).
Agrega a santiago_h3.parquet:
  poblacion_censo   personas (n_per) de las manzanas y entidades, repartidas por fracción de área
Cada manzana reparte sus personas entre los hexágonos que toca, en proporción al área compartida, así que
las sumas por comuna coinciden con el censo salvo en los bordes del área de estudio.
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyarrow.parquet as pq
from shapely import from_wkb

from . import config

log = logging.getLogger("verdeh3")


def leer_manzanas(ruta: Path, bbox) -> gpd.GeoDataFrame:
    t = pq.read_table(ruta, columns=["COMUNA", "n_per", "SHAPE"], filters=[("COD_REGION", "=", 13)]).to_pandas()
    g = gpd.GeoDataFrame(t[["COMUNA", "n_per"]], geometry=from_wkb(t["SHAPE"]), crs="EPSG:4674")  # SIRGAS 2000
    g = g[g["n_per"].fillna(0) > 0].to_crs(config.CRS_GEO)
    return g.cx[bbox[0]:bbox[2], bbox[1]:bbox[3]].to_crs(config.CRS_METRICO)


def repartir(hex_: gpd.GeoDataFrame, mz: gpd.GeoDataFrame) -> pd.Series:
    """Personas por h3, repartidas por fracción del área de cada manzana."""
    mz = mz.assign(mz_id=range(len(mz)), area_mz=mz.area)
    inter = gpd.overlay(hex_[["h3", "geometry"]].to_crs(config.CRS_METRICO), mz, how="intersection",
                        keep_geom_type=True)
    inter["p"] = inter["n_per"] * inter.area / inter["area_mz"]
    return inter.groupby("h3")["p"].sum()


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--salida", type=Path, default=Path("datos/salida_h3_gs"))
    p.add_argument("--manzanas", type=Path,
                   default=Path("cache/censo2024/Cartografia_censo2024_Pais_Manzanas.parquet"))
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    ruta = a.salida / "santiago_h3.parquet"
    tabla = gpd.read_parquet(ruta)
    mz = leer_manzanas(a.manzanas, tabla.total_bounds)
    log.info("%d manzanas con %d personas en el área", len(mz), mz["n_per"].sum())
    partes = []
    for r, g in tabla.groupby("res"):
        g = g.copy()
        g["poblacion_censo"] = g["h3"].map(repartir(g, mz)).fillna(0).round(1)
        partes.append(g)
        log.info("res %d: %d personas en %d hexágonos", r, g["poblacion_censo"].sum(), len(g))
    tabla = gpd.GeoDataFrame(pd.concat(partes).sort_index(), crs=tabla.crs)
    geom = tabla.pop("geometry")
    gpd.GeoDataFrame(tabla.assign(geometry=geom), crs=geom.crs).to_parquet(ruta, index=False)


if __name__ == "__main__":
    main()
