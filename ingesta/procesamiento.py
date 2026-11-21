"""Limpieza del grafo y cálculo de atributos base por calle (sin red: testeable offline)."""
from __future__ import annotations

import logging

import geopandas as gpd
import networkx as nx
import numpy as np
import osmnx as ox
import pandas as pd
from shapely import STRtree

from . import config

log = logging.getLogger(__name__)

TIPO_VIA = {
    "pedestrian": "peatonal", "footway": "peatonal", "path": "peatonal", "steps": "peatonal",
    "living_street": "peatonal", "track": "peatonal", "cycleway": "peatonal", "corridor": "peatonal",
    "residential": "local", "service": "local", "unclassified": "local", "road": "local",
    "tertiary": "colectora", "tertiary_link": "colectora", "secondary": "colectora",
    "secondary_link": "colectora",
    "primary": "troncal", "primary_link": "troncal", "trunk": "troncal", "trunk_link": "troncal",
}

PESOS_USO_SOCIAL = {"educacion": 0.30, "salud": 0.25, "metro": 0.25,
                    "paradero": 0.10, "adulto_mayor": 0.10}


def _primero(v):
    return v[0] if isinstance(v, list) and v else v


def _a_texto(v):
    if isinstance(v, (list, tuple, set)):
        return ";".join(str(x) for x in v)
    return v


# --------------------------------------------------------------------------- grafo
def preparar_grafo(G: nx.MultiDiGraph, consolidar_tol_m: float | None = None) -> nx.MultiGraph:
    """Simplifica, deja la componente conexa principal, proyecta a UTM 19S y pasa a no dirigido."""
    n0, m0 = G.number_of_nodes(), G.number_of_edges()
    if not G.graph.get("simplified"):
        G = ox.simplify_graph(G)
    G = ox.truncate.largest_component(G, strongly=False)
    G = ox.project_graph(G, to_crs=config.CRS_METRICO)
    if consolidar_tol_m:
        log.info("Consolidando intersecciones (tolerancia %.1f m)", consolidar_tol_m)
        G = ox.consolidate_intersections(G, tolerance=consolidar_tol_m, rebuild_graph=True,
                                         dead_ends=False, reconnect_edges=True)
    Gu = ox.convert.to_undirected(G)
    log.info("Grafo: %d nodos / %d aristas crudas -> %d nodos / %d aristas limpias",
             n0, m0, Gu.number_of_nodes(), Gu.number_of_edges())
    return Gu


# ------------------------------------------------------------------- áreas verdes
def limpiar_areas_verdes(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    cols = ["leisure", "landuse", "place", "name"]
    if gdf.empty:
        return gpd.GeoDataFrame(columns=["av_id", "tipo", "nombre", "area_m2", "consolidado", "geometry"],
                                geometry="geometry", crs=config.CRS_METRICO)
    gdf = gdf[gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    for c in cols:
        if c not in gdf.columns:
            gdf[c] = None
    gdf = gdf.to_crs(config.CRS_METRICO)
    gdf["tipo"] = gdf["leisure"].fillna(gdf["landuse"]).fillna(gdf["place"])
    gdf["nombre"] = gdf["name"]
    gdf["geometry"] = gdf.geometry.make_valid()
    gdf["area_m2"] = gdf.area
    # Pasto suelto pequeño (bandejones, jardineras) no es un área verde funcional.
    gdf = gdf[~((gdf["tipo"] == "grass") & (gdf["area_m2"] < 500)) & (gdf["area_m2"] >= 100)]
    gdf["consolidado"] = (gdf["area_m2"] >= config.AREA_PARQUE_CONSOLIDADO_M2) & \
        gdf["tipo"].isin(["park", "garden", "nature_reserve", "recreation_ground", "village_green", "square", "forest"])
    gdf = gdf.reset_index()
    gdf["osm_id"] = gdf["element"].astype(str) + "/" + gdf["id"].astype(str) if "element" in gdf else None
    gdf = gdf.sort_values("area_m2", ascending=False).reset_index(drop=True)
    gdf["av_id"] = np.arange(len(gdf))
    return gdf[["av_id", "osm_id", "tipo", "nombre", "area_m2", "consolidado", "geometry"]]


# ------------------------------------------------------------ puntos de interés
def _col(gdf, c):
    return gdf[c] if c in gdf.columns else pd.Series(None, index=gdf.index, dtype=object)


def limpiar_poi(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if gdf.empty:
        return gpd.GeoDataFrame(columns=["poi_id", "categoria", "subtipo", "nombre", "geometry"],
                                geometry="geometry", crs=config.CRS_METRICO)
    gdf = gdf.to_crs(config.CRS_METRICO).copy()
    amenity, railway, pt = _col(gdf, "amenity"), _col(gdf, "railway"), _col(gdf, "public_transport")
    station, subway, bus = _col(gdf, "station"), _col(gdf, "subway"), _col(gdf, "bus")
    highway, healthcare, social = _col(gdf, "highway"), _col(gdf, "healthcare"), _col(gdf, "social_facility")

    es_metro = (railway == "subway_entrance") | (station == "subway") | (subway == "yes")
    condiciones = [
        amenity.isin(["school", "kindergarten"]),
        amenity.isin(["college", "university"]),
        amenity.isin(["hospital", "clinic", "doctors"]) | healthcare.notna(),
        social == "nursing_home",
        es_metro,
        railway.isin(["station", "halt"]),
        (highway == "bus_stop") | ((pt == "platform") & (bus == "yes")),
    ]
    categorias = ["educacion", "educacion_superior", "salud", "adulto_mayor", "metro", "tren", "paradero"]
    gdf["categoria"] = np.select(condiciones, categorias, default="otro")
    gdf = gdf[gdf["categoria"] != "otro"]
    gdf["subtipo"] = amenity.fillna(railway).fillna(highway).fillna(healthcare).fillna(pt).reindex(gdf.index)
    gdf["nombre"] = _col(gdf, "name")
    gdf["geometry"] = gdf.geometry.representative_point()
    gdf = gdf.reset_index(drop=True)
    gdf["poi_id"] = np.arange(len(gdf))
    return gdf[["poi_id", "categoria", "subtipo", "nombre", "geometry"]]


# ------------------------------------------------------------ atributos por calle
def _ancho_osm(v) -> float:
    v = _primero(v)
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return np.nan
    try:
        return float(str(v).replace(",", ".").replace("m", "").strip())
    except ValueError:
        return np.nan


def _vereda(row) -> str:
    if row["tipo_via"] == "peatonal":
        return "via_peatonal"
    for c in ("sidewalk", "sidewalk:both", "sidewalk:left", "sidewalk:right"):
        v = _primero(row.get(c))
        if isinstance(v, str):
            if v in ("both", "left", "right", "yes"):
                return "si"
            if v in ("no", "none"):
                return "no"
            if v == "separate":
                return "separada"
    return "sin_dato"


def _distancia_nearest(origen: gpd.GeoDataFrame, destino: gpd.GeoDataFrame, max_m: float) -> pd.Series:
    if destino.empty:
        return pd.Series(np.nan, index=origen.index)
    j = gpd.sjoin_nearest(origen[["geometry"]], destino[["geometry"]], how="left",
                          max_distance=max_m, distance_col="d")
    return j.groupby(level=0)["d"].min().reindex(origen.index)


def _conteo_radio(puntos: gpd.GeoSeries, destino: gpd.GeoDataFrame, radio: float) -> np.ndarray:
    if destino.empty:
        return np.zeros(len(puntos), dtype=int)
    arbol = STRtree(destino.geometry.values)
    idx_origen, _ = arbol.query(puntos.values, predicate="dwithin", distance=radio)
    return np.bincount(idx_origen, minlength=len(puntos))


def atributos_aristas(G: nx.MultiGraph, areas: gpd.GeoDataFrame, poi: gpd.GeoDataFrame,
                      comunas: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    nodos, aristas = ox.graph_to_gdfs(G)
    aristas = aristas.reset_index()
    aristas["edge_id"] = aristas["u"].astype(str) + "-" + aristas["v"].astype(str) + "-" + aristas["key"].astype(str)
    aristas["highway"] = aristas["highway"].map(_primero)
    aristas["tipo_via"] = aristas["highway"].map(TIPO_VIA).fillna("otro")
    aristas["longitud_m"] = aristas.geometry.length.round(2)
    for c in config.TAGS_VIA_EXTRA + ["width", "name", "lit", "surface"]:
        if c not in aristas.columns:
            aristas[c] = None
    aristas["vereda"] = aristas.apply(_vereda, axis=1)
    ancho_tag = aristas["sidewalk:width"].map(_ancho_osm)
    ancho_tag = ancho_tag.fillna(aristas["width"].map(_ancho_osm).where(aristas["tipo_via"] == "peatonal"))
    defecto = aristas["highway"].map(config.ANCHO_VEREDA_DEFECTO_M).fillna(config.ANCHO_VEREDA_GENERICO_M)
    aristas["ancho_vereda_m"] = ancho_tag.clip(0.5, 30).fillna(defecto)
    aristas["ancho_fuente"] = np.where(ancho_tag.notna(), "osm", "supuesto")
    aristas["nombre"] = aristas["name"].map(_a_texto)

    medio = aristas.geometry.interpolate(0.5, normalized=True)
    medio_gdf = gpd.GeoDataFrame(geometry=medio, crs=aristas.crs)

    # Comuna de cada tramo (por su punto medio).
    com = comunas.to_crs(aristas.crs)[["comuna", "geometry"]]
    j = gpd.sjoin(medio_gdf, com, how="left", predicate="within")
    aristas["comuna"] = j.groupby(level=0)["comuna"].first().reindex(aristas.index)

    # Relación con áreas verdes.
    lineas = aristas[["geometry"]]
    aristas["dist_area_verde_m"] = _distancia_nearest(lineas, areas, 3000).round(1)
    consolidadas = areas[areas["consolidado"]] if not areas.empty else areas
    aristas["dist_parque_m"] = _distancia_nearest(lineas, consolidadas, 3000).round(1)
    aristas["adyacente_parque"] = aristas["dist_parque_m"].fillna(np.inf) <= config.RADIO_ADYACENCIA_PARQUE_M

    # Factor de uso social U_e: POIs a menos de 300 m del tramo.
    u = np.zeros(len(aristas))
    for cat, peso in PESOS_USO_SOCIAL.items():
        sub = poi[poi["categoria"] == cat]
        n = _conteo_radio(medio, sub, config.RADIO_USO_SOCIAL_M)
        aristas[f"n_{cat}_300m"] = n
        aristas[f"dist_{cat}_m"] = _distancia_nearest(medio_gdf, sub, 3000).round(1)
        u += peso * (n > 0)
    aristas["u_social"] = u.round(3)

    # Columnas que llenan los bloques siguientes.
    for c in ("ndvi", "lst", "d_deficit", "costo"):
        aristas[c] = np.nan

    columnas = ["edge_id", "u", "v", "key", "osmid", "nombre", "highway", "tipo_via", "comuna",
                "longitud_m", "vereda", "ancho_vereda_m", "ancho_fuente", "surface", "lit",
                "dist_area_verde_m", "dist_parque_m", "adyacente_parque", "u_social"]
    columnas += [c for c in aristas.columns if c.startswith(("n_", "dist_")) and c not in columnas]
    columnas += ["ndvi", "lst", "d_deficit", "costo", "geometry"]
    aristas = aristas[columnas]
    for c in aristas.columns:
        if c != "geometry" and aristas[c].dtype == object:
            aristas[c] = aristas[c].map(_a_texto)

    # Nodos: comuna y parque consolidado al que tocan (terminales del Bloque 3).
    nodos = nodos.reset_index()[["osmid", "x", "y", "street_count", "geometry"]].rename(columns={"osmid": "node_id"})
    jn = gpd.sjoin(nodos[["geometry"]], com, how="left", predicate="within")
    nodos["comuna"] = jn.groupby(level=0)["comuna"].first().reindex(nodos.index)
    if not consolidadas.empty:
        jp = gpd.sjoin_nearest(nodos[["geometry"]], consolidadas[["av_id", "geometry"]], how="left",
                               max_distance=20, distance_col="d")
        nodos["parque_av_id"] = jp.sort_values("d").groupby(level=0)["av_id"].first().reindex(nodos.index)
    else:
        nodos["parque_av_id"] = np.nan
    return aristas, nodos


def volcar_atributos_en_grafo(G: nx.MultiGraph, aristas: gpd.GeoDataFrame, nodos: gpd.GeoDataFrame) -> None:
    """Copia los atributos calculados al grafo NetworkX que usará el Bloque 3."""
    attrs = aristas.drop(columns=["geometry", "osmid"]).set_index(["u", "v", "key"])
    nx.set_edge_attributes(G, attrs.to_dict("index"))
    nattrs = nodos.set_index("node_id")[["comuna", "parque_av_id"]]
    nx.set_node_attributes(G, nattrs.to_dict("index"))
