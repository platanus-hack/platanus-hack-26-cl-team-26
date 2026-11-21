"""Temperatura superficial Landsat actualizable: busca la escena más reciente y recalcula por hexágono.

python -m verdeh3.landsat                  # modo verano: última escena de diciembre a febrero -> lst_c, lst_fecha
python -m verdeh3.landsat --modo ultima    # última disponible -> lst_c_ultima, lst_fecha_ultima (solo para mostrar)

El índice usa siempre el modo verano: comparar barrios con una escena de invierno subestima el calor.
Escenas Landsat 8 o 9 Collection 2 L2 de Planetary Computer con menos de 10% de nubes que cubran todo el
área. Cada escena queda en caché como lst_<id>.tif.
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box, shape

from . import config, fuentes, grilla

log = logging.getLogger("verdeh3")

DIAS_ULTIMA = 180


def ventana(modo: str, hoy: dt.date) -> str:
    if modo == "ultima":
        return f"{hoy - dt.timedelta(days=DIAS_ULTIMA)}/{hoy}"
    # Verano meteorológico (diciembre a febrero) más reciente ya empezado: dic(fin-1)..feb(fin).
    # Marzo queda fuera: la escena del 31-03-2026 da 6 °C menos de media que las de febrero.
    fin = hoy.year + 1 if hoy.month == 12 else hoy.year
    return f"{fin - 1}-12-01/{min(dt.date(fin, 3, 1) - dt.timedelta(days=1), hoy)}"


def escena_reciente(bbox, modo: str, hoy: dt.date):
    rango = ventana(modo, hoy)
    items = fuentes._stac().search(
        collections=["landsat-c2-l2"], bbox=bbox, datetime=rango,
        query={"eo:cloud_cover": {"lt": config.NUBES_MAX_LANDSAT}, "platform": {"in": ["landsat-8", "landsat-9"]}},
    ).items()
    cubren = [i for i in items if shape(i.geometry).contains(box(*bbox))]
    if not cubren:
        raise SystemExit(f"Sin escenas Landsat con nubes < {config.NUBES_MAX_LANDSAT}% que cubran el área en {rango}")
    it = max(cubren, key=lambda i: i.datetime)
    log.info("Escena %s (%s, nubes %.1f%%) en %s", it.id, it.datetime.date(), it.properties["eo:cloud_cover"], rango)
    return it


def lst_escena(it, bbox, cache: Path):
    ruta = cache / f"lst_{it.id}.tif"
    if not ruta.exists():
        st, t, crs = fuentes._leer_recorte(it.assets["lwir11"].href, bbox, 1, "nearest")
        lst = st.astype("float64") * 0.00341802 + 149.0 - 273.15  # Collection 2 L2 -> °C
        lst[st == 0] = np.nan
        fuentes._guardar_tif(ruta, lst, t, crs, {"escena": it.id, "fecha": it.datetime.date()})
    return fuentes._leer_tif(ruta)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--modo", choices=["verano", "ultima"], default="verano")
    p.add_argument("--salida", type=Path, default=Path("datos/salida_h3_gs"))
    p.add_argument("--cache", type=Path, default=Path("datos/cache_gs"))
    p.add_argument("--hoy", type=dt.date.fromisoformat, default=dt.date.today())
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    ruta = a.salida / "santiago_h3.parquet"
    tabla = gpd.read_parquet(ruta)
    bbox = tuple(round(v, 5) for v in tabla.total_bounds)

    it = escena_reciente(bbox, a.modo, a.hoy)
    arr, t, crs, _ = lst_escena(it, bbox, a.cache)
    sufijo = "" if a.modo == "verano" else "_ultima"
    hexs = {r: g.drop(columns=[f"lst_c{sufijo}", f"lst_c{sufijo}_max"], errors="ignore").copy()
            for r, g in tabla.groupby("res")}
    grilla.agregar_raster(hexs, arr, t, crs, f"lst_c{sufijo}", stats=("mean", "max"))
    for h in hexs.values():
        h.rename(columns={f"lst_c{sufijo}_mean": f"lst_c{sufijo}"}, inplace=True)  # noqa: PD002
        h[f"lst_fecha{sufijo}"] = str(it.datetime.date())
        h[f"lst_escena{sufijo}"] = it.id
    tabla = gpd.GeoDataFrame(pd.concat(hexs.values()).sort_index(), crs=tabla.crs)
    geom = tabla.pop("geometry")
    gpd.GeoDataFrame(tabla.assign(geometry=geom), crs=geom.crs).to_parquet(ruta, index=False)
    for r, g in tabla.groupby("res"):
        log.info("res %d: lst_c%s media %.1f °C, %d sin dato", r, sufijo, g[f"lst_c{sufijo}"].mean(),
                 g[f"lst_c{sufijo}"].isna().sum())


if __name__ == "__main__":
    main()
