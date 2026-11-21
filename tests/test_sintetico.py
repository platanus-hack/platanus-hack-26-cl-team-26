"""Prueba offline del procesamiento con una red sintética con la forma de la de OSMnx.

Uso: python -m tests.test_sintetico [N]   (N = cuadras por lado, por defecto 40)
No requiere internet: valida limpieza, atributos y escritura del GeoPackage.
"""
import sys
import tempfile
import time
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from shapely.geometry import Point, box

from ingesta import procesamiento
from ingesta.pipeline import cargar_grafo, escribir_salidas

LON0, LAT0 = -70.62, -33.44  # Providencia / Ñuñoa
PASO = 0.0011  # ~110 m por cuadra


def red_sintetica(n: int) -> nx.MultiDiGraph:
    G = nx.MultiDiGraph(crs="epsg:4326")
    rng = np.random.default_rng(0)
    nid = lambda i, j: i * 10_000 + j  # noqa: E731
    # Nodos cada media cuadra: los intermedios deben desaparecer al simplificar.
    for i in range(2 * n + 1):
        for j in range(2 * n + 1):
            G.add_node(nid(i, j), x=LON0 + i * PASO / 2, y=LAT0 + j * PASO / 2, street_count=0)
    way = 0
    for horizontal in (True, False):
        for k in range(0, 2 * n + 1, 2):
            way += 1
            hw = "primary" if k % 20 == 0 else rng.choice(["residential", "residential", "tertiary", "footway"])
            tags = {"osmid": way, "highway": hw, "oneway": False, "name": f"Calle {way}"}
            if rng.random() < 0.3:
                tags["sidewalk"] = rng.choice(["both", "no", "separate"])
            if rng.random() < 0.1:
                tags["sidewalk:width"] = "2.5"
            for s in range(2 * n):
                a, b = ((s, k), (s + 1, k)) if horizontal else ((k, s), (k, s + 1))
                u, v = nid(*a), nid(*b)
                for x, y, rev in ((u, v, False), (v, u, True)):
                    G.add_edge(x, y, length=55.0, reversed=rev, **tags)
    # Un islote desconectado que debe eliminarse.
    G.add_node(9_000_001, x=LON0 - 0.05, y=LAT0, street_count=1)
    G.add_node(9_000_002, x=LON0 - 0.051, y=LAT0, street_count=1)
    G.add_edge(9_000_001, 9_000_002, osmid=999999, highway="footway", length=90.0, oneway=False, reversed=False)
    G.remove_nodes_from([n_ for n_, d in G.degree() if d == 0])
    return G


def features_sinteticos(n: int):
    ext = n * PASO
    parques = gpd.GeoDataFrame(
        {"leisure": ["park", "park", None, "playground"], "landuse": [None, None, "grass", None],
         "name": ["Parque A", "Plaza B", "bandejon", "Juegos"]},
        geometry=[box(LON0 + 0.1 * ext, LAT0 + 0.1 * ext, LON0 + 0.25 * ext, LAT0 + 0.25 * ext),
                  box(LON0 + 0.7 * ext, LAT0 + 0.7 * ext, LON0 + 0.8 * ext, LAT0 + 0.8 * ext),
                  box(LON0 + 0.5 * ext, LAT0 + 0.5 * ext, LON0 + 0.5 * ext + 0.0001, LAT0 + 0.5 * ext + 0.0001),
                  Point(LON0 + 0.4 * ext, LAT0 + 0.4 * ext).buffer(0.0002)],
        crs="EPSG:4326",
    )
    parques.index = pd.MultiIndex.from_tuples([("way", i) for i in range(len(parques))], names=["element", "id"])
    rng = np.random.default_rng(1)
    filas = []
    for amen, rail, hw, sub in [("school", None, None, None), ("clinic", None, None, None),
                                (None, "subway_entrance", None, None), (None, None, "bus_stop", None),
                                (None, "station", None, "subway")]:
        for _ in range(max(3, n // 4)):
            filas.append({"amenity": amen, "railway": rail, "highway": hw, "station": sub, "name": "x",
                          "geometry": Point(LON0 + rng.random() * ext, LAT0 + rng.random() * ext)})
    poi = gpd.GeoDataFrame(filas, crs="EPSG:4326")
    comunas = gpd.GeoDataFrame({"comuna": ["Oeste", "Este"]},
                               geometry=[box(LON0 - 0.1, LAT0 - 0.1, LON0 + ext / 2, LAT0 + ext + 0.1),
                                         box(LON0 + ext / 2, LAT0 - 0.1, LON0 + ext + 0.1, LAT0 + ext + 0.1)],
                               crs="EPSG:4326")
    return parques, poi, comunas


def main(n: int = 40):
    t0 = time.time()
    G = red_sintetica(n)
    parques, poi_raw, comunas = features_sinteticos(n)
    Gu = procesamiento.preparar_grafo(G)
    areas = procesamiento.limpiar_areas_verdes(parques)
    poi = procesamiento.limpiar_poi(poi_raw)
    aristas, nodos = procesamiento.atributos_aristas(Gu, areas, poi, comunas)
    procesamiento.volcar_atributos_en_grafo(Gu, aristas, nodos)

    esperadas_nodos = (n + 1) ** 2
    # Las 4 esquinas tienen grado 2 y OSMnx las puede absorber al simplificar.
    assert esperadas_nodos - 4 <= Gu.number_of_nodes() <= esperadas_nodos, (Gu.number_of_nodes(), esperadas_nodos)
    assert Gu.number_of_edges() <= 2 * n * (n + 1)
    assert 9_000_001 not in Gu, "el islote desconectado debía eliminarse"
    assert aristas.crs.to_epsg() == 32719
    assert aristas["edge_id"].is_unique
    assert set(aristas["comuna"].dropna()) == {"Oeste", "Este"} and aristas["comuna"].notna().all()
    assert aristas["adyacente_parque"].any() and aristas["u_social"].between(0, 1).all()
    assert (aristas["ancho_fuente"] == "osm").any() and (aristas["ancho_vereda_m"] > 0).all()
    assert set(areas["nombre"]) >= {"Parque A", "Plaza B"} and "bandejon" not in set(areas["nombre"])
    assert set(poi["categoria"]) == {"educacion", "salud", "metro", "paradero"}
    assert nodos["parque_av_id"].notna().any()
    u, v, k = next(iter(Gu.edges(keys=True)))
    assert "u_social" in Gu.edges[u, v, k] and "comuna" in Gu.nodes[u]

    with tempfile.TemporaryDirectory() as d:
        poly = comunas.union_all()
        r = escribir_salidas(Path(d), Gu, aristas, nodos, areas, poi, comunas, poly)
        capas = gpd.list_layers(Path(d) / "grafo_piloto.gpkg")["name"].tolist()
        assert capas == ["aristas", "nodos", "areas_verdes", "poi", "comunas", "area_estudio"], capas
        leida = gpd.read_file(Path(d) / "grafo_piloto.gpkg", layer="aristas")
        assert len(leida) == len(aristas)
        G2 = cargar_grafo(Path(d) / "grafo_piloto.pkl")
        assert G2.number_of_edges() == Gu.number_of_edges()
    print(f"OK n={n}: {r['nodos']} nodos, {r['aristas']} aristas, {r['km_red']} km, "
          f"{r['parques_consolidados']} parques consolidados, POIs {r['poi_por_categoria']} "
          f"en {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 40)
