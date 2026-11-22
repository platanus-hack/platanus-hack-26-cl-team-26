"""Población del Censo 2024 (INE) por hexágono, repartida desde las manzanas por área.

python -m verdeh3.censo --salida datos/salida_h3_gs --manzanas cache/censo2024/Cartografia_censo2024_Pais_Manzanas.parquet

La capa sale del zip "Cartografía País Censo 2024 (geoparquet)" de censo2024.ine.gob.cl (no se versiona).
Agrega a santiago_h3.parquet:
  poblacion_censo   personas (n_per) de las manzanas y entidades, repartidas por fracción de área
  censo_*           conteos para la vulnerabilidad (ver VARIABLES y verdeh3.contrato.vulnerabilidad),
                    repartidos igual que las personas
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

# Conteos por manzana para la vulnerabilidad → columna en santiago_h3.parquet. La escolaridad es un
# promedio, así que se reparte como suma ponderada por personas (escolaridad × personas) y su denominador.
VARIABLES = {
    "n_edad_60_mas": "censo_60_mas",
    "n_edad_0_5": "censo_0_5",
    "n_discapacidad": "censo_discapacidad",
    "n_vp_ocupada": "censo_viv_ocupadas",
    "n_viv_hacinadas": "censo_viv_hacinadas",
    "n_viv_irrecuperables": "censo_viv_irrecuperables",
    "escolaridad_x_per": "censo_escolaridad_x_per",
    "per_con_escolaridad": "censo_per_escolaridad",
}
LEIDAS = ["n_edad_60_mas", "n_edad_0_5", "n_discapacidad", "n_vp_ocupada", "n_viv_hacinadas", "n_viv_irrecuperables",
          "prom_escolaridad18"]


def leer_manzanas(ruta: Path, bbox) -> gpd.GeoDataFrame:
    t = pq.read_table(ruta, columns=["COMUNA", "n_per", *LEIDAS, "SHAPE"],
                      filters=[("COD_REGION", "=", 13)]).to_pandas()
    esc = t["prom_escolaridad18"]
    t["escolaridad_x_per"] = (esc * t["n_per"]).fillna(0)
    t["per_con_escolaridad"] = t["n_per"].where(esc.notna(), 0)
    datos = ["COMUNA", "n_per", *(c for c in VARIABLES if c != "n_per")]
    g = gpd.GeoDataFrame(t[datos], geometry=from_wkb(t["SHAPE"]), crs="EPSG:4674")  # SIRGAS 2000
    g = g[g["n_per"].fillna(0) > 0].to_crs(config.CRS_GEO)
    return g.cx[bbox[0]:bbox[2], bbox[1]:bbox[3]].to_crs(config.CRS_METRICO)


def repartir(hex_: gpd.GeoDataFrame, mz: gpd.GeoDataFrame, columnas=("n_per",)) -> pd.DataFrame:
    """Sumas por h3 de las columnas de cada manzana, repartidas por fracción del área de la manzana."""
    mz = mz.assign(mz_id=range(len(mz)), area_mz=mz.area)
    inter = gpd.overlay(hex_[["h3", "geometry"]].to_crs(config.CRS_METRICO), mz, how="intersection",
                        keep_geom_type=True)
    frac = inter.area / inter["area_mz"]
    return pd.DataFrame({c: inter[c].fillna(0) * frac for c in columnas}).groupby(inter["h3"]).sum()


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
        sumas = repartir(g, mz, ["n_per", *VARIABLES])
        g["poblacion_censo"] = g["h3"].map(sumas["n_per"]).fillna(0).round(1)
        for origen, destino in VARIABLES.items():
            g[destino] = g["h3"].map(sumas[origen]).fillna(0).round(2)
        partes.append(g)
        log.info("res %d: %d personas en %d hexágonos", r, g["poblacion_censo"].sum(), len(g))
    tabla = gpd.GeoDataFrame(pd.concat(partes).sort_index(), crs=tabla.crs)
    geom = tabla.pop("geometry")
    gpd.GeoDataFrame(tabla.assign(geometry=geom), crs=geom.crs).to_parquet(ruta, index=False)


if __name__ == "__main__":
    main()
