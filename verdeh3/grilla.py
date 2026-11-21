"""Grilla H3 y agregación de capas a hexágonos (sin red: testeable offline)."""
from __future__ import annotations

import logging

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
from pyproj import Transformer
from shapely.geometry import Polygon

from . import config

log = logging.getLogger(__name__)


# ------------------------------------------------------------------------- grilla
def _hex_poligono(c: str) -> Polygon:
    return Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(c)])


def construir_grilla(comunas: gpd.GeoDataFrame, res: int, area_estudio) -> gpd.GeoDataFrame:
    """Hexágonos que tocan el área de estudio, con la comuna donde cae su centroide."""
    margen = h3.average_hexagon_edge_length(res, unit="m") * 1.2 / 111_000  # grados aprox.
    celdas = set(h3.geo_to_cells(area_estudio.buffer(margen), res))
    gdf = gpd.GeoDataFrame({"h3": sorted(celdas)}, geometry=[_hex_poligono(c) for c in sorted(celdas)],
                           crs=config.CRS_GEO)
    gdf = gdf[gdf.intersects(area_estudio)].reset_index(drop=True)
    gdf["res"] = res
    lat, lng = zip(*[h3.cell_to_latlng(c) for c in gdf["h3"]]) if len(gdf) else ((), ())
    gdf["lat"], gdf["lng"] = lat, lng
    if res > min(config.RESOLUCIONES):
        gdf[f"h3_r{min(config.RESOLUCIONES)}"] = [h3.cell_to_parent(c, min(config.RESOLUCIONES)) for c in gdf["h3"]]

    m = gdf.to_crs(config.CRS_METRICO)
    gdf["area_m2"] = m.area.round(0)
    gdf["frac_en_estudio"] = (m.intersection(gpd.GeoSeries([area_estudio], crs=config.CRS_GEO)
                                             .to_crs(config.CRS_METRICO).iloc[0]).area / m.area).round(3)
    cent = gpd.GeoDataFrame(geometry=gpd.points_from_xy(gdf["lng"], gdf["lat"]), crs=config.CRS_GEO)
    com = comunas[["comuna", "geometry"]].to_crs(config.CRS_GEO)
    j = gpd.sjoin(cent, com, how="left", predicate="within")
    gdf["comuna"] = j.groupby(level=0)["comuna"].first().reindex(gdf.index)
    sin = gdf["comuna"].isna()
    if sin.any():  # bordes: comuna más cercana
        jn = gpd.sjoin_nearest(cent[sin].to_crs(config.CRS_METRICO), com.to_crs(config.CRS_METRICO), how="left")
        gdf.loc[sin, "comuna"] = jn.groupby(level=0)["comuna"].first()
    log.info("Grilla res %d: %d hexágonos", res, len(gdf))
    return gdf


# --------------------------------------------------------------- áreas verdes
def agregar_areas_verdes(hex_: gpd.GeoDataFrame, areas: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """areas: salida de ingesta.procesamiento.limpiar_areas_verdes (EPSG:32719)."""
    h = hex_.to_crs(config.CRS_METRICO)
    if areas.empty:
        hex_["area_verde_m2"] = 0.0
        hex_["pct_area_verde"] = 0.0
        hex_["n_parques_consolidados"] = 0
        hex_["dist_parque_m"] = np.nan
        return hex_
    disueltas = gpd.GeoDataFrame(geometry=[areas.union_all()], crs=areas.crs)
    inter = gpd.overlay(h[["h3", "geometry"]], disueltas, how="intersection", keep_geom_type=True)
    av = inter.assign(a=inter.area).groupby("h3")["a"].sum()
    hex_["area_verde_m2"] = hex_["h3"].map(av).fillna(0).round(0)
    hex_["pct_area_verde"] = (100 * hex_["area_verde_m2"] / hex_["area_m2"]).clip(0, 100).round(2)

    cons = areas[areas["consolidado"]]
    if cons.empty:
        hex_["n_parques_consolidados"] = 0
        hex_["dist_parque_m"] = np.nan
        return hex_
    jp = gpd.sjoin(h[["h3", "geometry"]], cons[["av_id", "geometry"]], how="inner", predicate="intersects")
    hex_["n_parques_consolidados"] = hex_["h3"].map(jp.groupby("h3")["av_id"].nunique()).fillna(0).astype(int)
    cent = gpd.GeoDataFrame({"h3": hex_["h3"]}, geometry=gpd.points_from_xy(hex_["lng"], hex_["lat"]),
                            crs=config.CRS_GEO).to_crs(config.CRS_METRICO)
    jd = gpd.sjoin_nearest(cent, cons[["geometry"]], how="left", distance_col="d")
    hex_["dist_parque_m"] = jd.groupby(level=0)["d"].min().reindex(hex_.index).round(1)
    return hex_


# --------------------------------------------------------------------- POIs
def agregar_poi(hex_: gpd.GeoDataFrame, poi: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """poi: salida de ingesta.procesamiento.limpiar_poi (puntos EPSG:32719 con 'categoria')."""
    res = int(hex_["res"].iloc[0])
    cent = gpd.GeoDataFrame(geometry=gpd.points_from_xy(hex_["lng"], hex_["lat"]),
                            crs=config.CRS_GEO).to_crs(config.CRS_METRICO)
    p_ll = poi.to_crs(config.CRS_GEO)
    celdas_poi = pd.Series([h3.latlng_to_cell(pt.y, pt.x, res) for pt in p_ll.geometry], index=poi.index)
    for cat in config.CATEGORIAS_POI:
        sub = poi[poi["categoria"] == cat]
        hex_[f"n_{cat}"] = hex_["h3"].map(celdas_poi[sub.index].value_counts()).fillna(0).astype(int)
        if sub.empty:
            hex_[f"dist_{cat}_m"] = np.nan
            hex_[f"cerca_{cat}"] = False
            continue
        jd = gpd.sjoin_nearest(cent, sub[["geometry"]], how="left", distance_col="d")
        hex_[f"dist_{cat}_m"] = jd.groupby(level=0)["d"].min().reindex(hex_.index).round(1).values
        hex_[f"cerca_{cat}"] = hex_[f"dist_{cat}_m"] <= config.RADIO_CERCANIA_M
    return hex_


# -------------------------------------------------------------------- rásters
def celdas_de_pixeles(transform, crs, shape, res_list, mascara=None) -> dict[int, np.ndarray]:
    """Celda H3 del centro de cada píxel (para las resoluciones pedidas)."""
    filas, cols = np.nonzero(mascara if mascara is not None else np.ones(shape, bool))
    xs, ys = transform * (cols + 0.5, filas + 0.5)
    lng, lat = Transformer.from_crs(crs, config.CRS_GEO, always_xy=True).transform(xs, ys)
    salida = {"filas": filas, "cols": cols}
    for r in res_list:
        salida[r] = np.array([h3.latlng_to_cell(a, b, r) for a, b in zip(lat, lng)])
    return salida


def agregar_raster(hex_por_res: dict[int, gpd.GeoDataFrame], arr: np.ndarray, transform, crs,
                   nombre: str, stats=("mean",), nodata=np.nan) -> None:
    """Agrega un ráster a cada grilla. stats: mean, max, p90, sum, count."""
    valido = np.isfinite(arr) if np.isnan(nodata) else (arr != nodata) & np.isfinite(arr)
    pix = celdas_de_pixeles(transform, crs, arr.shape, list(hex_por_res), valido)
    valores = arr[pix["filas"], pix["cols"]].astype("float64")
    for res, hex_ in hex_por_res.items():
        df = pd.DataFrame({"h3": pix[res], "v": valores})
        df = df[df["h3"].isin(set(hex_["h3"]))]
        g = df.groupby("h3")["v"]
        for s in stats:
            col = f"{nombre}_{s}" if len(stats) > 1 or s != "mean" else nombre
            if s == "p90":
                serie = g.quantile(0.9)
            elif s == "count":
                serie = g.size()
            else:
                serie = getattr(g, s)()
            hex_[col] = hex_["h3"].map(serie)
            if s in ("sum", "count"):
                hex_[col] = hex_[col].fillna(0)
            hex_[col] = hex_[col].round(4)


def finalizar(hex_por_res: dict[int, gpd.GeoDataFrame]) -> gpd.GeoDataFrame:
    for hex_ in hex_por_res.values():
        if "poblacion" in hex_:
            hex_["densidad_hab_km2"] = (hex_["poblacion"] / (hex_["area_m2"] / 1e6)).round(1)
    todo = pd.concat(hex_por_res.values(), ignore_index=True)
    columnas_primero = ["h3", "res", "comuna", "lat", "lng", "area_m2", "frac_en_estudio"]
    otras = [c for c in todo.columns if c not in columnas_primero + ["geometry"]]
    return gpd.GeoDataFrame(todo[columnas_primero + otras + ["geometry"]], crs=config.CRS_GEO)
