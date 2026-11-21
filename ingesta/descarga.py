"""Descarga desde OpenStreetMap (Nominatim + Overpass) con caché en disco.

Toda respuesta de Overpass/Nominatim queda en `cache/osmnx/`, así que si una
descarga se corta basta con volver a ejecutar el pipeline: solo pide lo que falta.
"""
from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import networkx as nx
import osmnx as ox
import pandas as pd
from shapely.geometry import box

from . import config

log = logging.getLogger(__name__)


def configurar_osmnx(dir_cache: Path) -> None:
    ox.settings.use_cache = True
    ox.settings.cache_folder = str(dir_cache / "osmnx")
    ox.settings.log_console = False
    ox.settings.requests_timeout = 600
    ox.settings.overpass_settings = "[out:json][timeout:{timeout}]{maxsize}"
    ox.settings.max_query_area_size = config.MAX_AREA_CONSULTA_M2
    tags = list(ox.settings.useful_tags_way)
    for t in config.TAGS_VIA_EXTRA:
        if t not in tags:
            tags.append(t)
    ox.settings.useful_tags_way = tags


def _geocodificar_comuna(nombre: str) -> gpd.GeoDataFrame:
    consultas = [config.CONSULTA_ALTERNATIVA.get(nombre), f"{nombre}, {config.REGION}"]
    marco = box(*config.BBOX_URBANO).buffer(0.3)
    for q in [c for c in consultas if c]:
        try:
            gdf = ox.geocode_to_gdf(q)
        except Exception as e:  # noqa: BLE001
            log.warning("Nominatim falló para %r: %s", q, e)
            continue
        geom = gdf.geometry.iloc[0]
        area_km2 = gpd.GeoSeries([geom], crs=config.CRS_GEO).to_crs(config.CRS_METRICO).area.iloc[0] / 1e6
        # Validación: polígono, dentro de Santiago y no la provincia/región entera.
        if geom.geom_type in ("Polygon", "MultiPolygon") and marco.contains(geom.centroid) and area_km2 < 1500:
            return gpd.GeoDataFrame({"comuna": [nombre], "area_km2": [area_km2]}, geometry=[geom], crs=config.CRS_GEO)
        log.warning("Resultado descartado para %r (%s, %.0f km²)", q, geom.geom_type, area_km2)
    raise RuntimeError(
        f"No se pudo geocodificar la comuna {nombre!r}. Agrega una consulta en "
        "config.CONSULTA_ALTERNATIVA o usa --comunas-archivo con límites oficiales."
    )


def obtener_comunas(nombres: list[str], archivo: Path | None, dir_cache: Path) -> gpd.GeoDataFrame:
    """Polígonos comunales. Usa un archivo local si se entrega (p. ej. DPA de IDE Chile)."""
    if archivo:
        gdf = gpd.read_file(archivo).to_crs(config.CRS_GEO)
        col = next((c for c in gdf.columns if c.lower() in ("comuna", "nom_comuna", "nombre", "name")), None)
        if col is None:
            raise ValueError(f"{archivo} no tiene columna de nombre de comuna")
        gdf = gdf.rename(columns={col: "comuna"})
        gdf = gdf[gdf["comuna"].str.lower().isin([n.lower() for n in nombres])]
        gdf["area_km2"] = gdf.to_crs(config.CRS_METRICO).area / 1e6
        return gdf[["comuna", "area_km2", "geometry"]].reset_index(drop=True)

    cache = dir_cache / "comunas.gpkg"
    previas = gpd.read_file(cache) if cache.exists() else None
    partes = []
    for n in nombres:
        if previas is not None and n in set(previas["comuna"]):
            partes.append(previas[previas["comuna"] == n])
            continue
        log.info("Geocodificando comuna %s", n)
        partes.append(_geocodificar_comuna(n))
    gdf = gpd.GeoDataFrame(pd.concat(partes, ignore_index=True), crs=config.CRS_GEO)
    todas = gdf if previas is None else gpd.GeoDataFrame(
        pd.concat([previas[~previas["comuna"].isin(gdf["comuna"])], gdf], ignore_index=True), crs=config.CRS_GEO)
    todas.to_file(cache, driver="GPKG")
    return gdf


def area_de_estudio(comunas: gpd.GeoDataFrame, recorte_urbano: bool):
    poly = comunas.union_all()
    if recorte_urbano:
        poly = poly.intersection(box(*config.BBOX_URBANO))
    return poly


def descargar_red_peatonal(poligono) -> nx.MultiDiGraph:
    """Red peatonal sin simplificar. Se simplifica una sola vez después, sobre el
    grafo completo, para que no queden cortes artificiales en los límites comunales."""
    log.info("Descargando red peatonal (Overpass, subdividido en celdas de %.0f km²)",
             config.MAX_AREA_CONSULTA_M2 / 1e6)
    return ox.graph_from_polygon(poligono, network_type="walk", simplify=False,
                                 retain_all=True, truncate_by_edge=True)


def descargar_features(poligono, tags: dict) -> gpd.GeoDataFrame:
    try:
        return ox.features_from_polygon(poligono, tags=tags)
    except ox._errors.InsufficientResponseError:
        return gpd.GeoDataFrame(geometry=[], crs=config.CRS_GEO)
