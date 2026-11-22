"""Red de calles del piloto (grafo NetworkX): python -m ingesta.pipeline [opciones]

Genera salida/grafo_piloto.gpkg (capas aristas, nodos, areas_verdes, poi, comunas,
area_estudio), salida/grafo_piloto.pkl (grafo NetworkX con atributos) y salida/resumen.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import pickle
import time
from pathlib import Path

import geopandas as gpd

from . import config, descarga, procesamiento

log = logging.getLogger("ingesta")


def _args():
    p = argparse.ArgumentParser(description="Ingesta geoespacial del Gran Santiago")
    p.add_argument("--comunas", nargs="+", help="Subconjunto de comunas (por defecto: las 34 del Gran Santiago)")
    p.add_argument("--extendido", action="store_true", help="Suma Padre Hurtado, Pirque y Calera de Tango")
    p.add_argument("--comunas-archivo", type=Path, help="Límites comunales locales (gpkg/shp) en vez de Nominatim")
    p.add_argument("--sin-recorte-urbano", action="store_true", help="No recortar a la mancha urbana")
    p.add_argument("--consolidar", type=float, metavar="TOL_M",
                   help="Fusiona intersecciones a menos de TOL_M metros (p. ej. 10). Reduce nodos ~30%%")
    p.add_argument("--salida", type=Path, default=Path("salida"))
    p.add_argument("--cache", type=Path, default=Path("datos/cache"))
    return p.parse_args()


def main():
    a = _args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    a.salida.mkdir(parents=True, exist_ok=True)
    a.cache.mkdir(parents=True, exist_ok=True)
    descarga.configurar_osmnx(a.cache)
    t0 = time.time()

    nombres = a.comunas or (config.COMUNAS_GRAN_SANTIAGO + (config.COMUNAS_EXTENDIDAS if a.extendido else []))
    comunas = descarga.obtener_comunas(nombres, a.comunas_archivo, a.cache)
    poly = descarga.area_de_estudio(comunas, recorte_urbano=not a.sin_recorte_urbano)
    log.info("Área de estudio: %d comunas, %.0f km²", len(comunas),
             gpd.GeoSeries([poly], crs=config.CRS_GEO).to_crs(config.CRS_METRICO).area.iloc[0] / 1e6)

    # Red peatonal cruda (con caché propia para no reconstruir el grafo en cada corrida).
    clave = hashlib.md5((poly.wkt + str(config.TAGS_VIA_EXTRA)).encode()).hexdigest()[:10]
    cruda = a.cache / f"red_cruda_{clave}.pkl"
    if cruda.exists():
        G = pickle.loads(cruda.read_bytes())
        log.info("Red cruda desde caché (%s)", cruda.name)
    else:
        G = descarga.descargar_red_peatonal(poly)
        cruda.write_bytes(pickle.dumps(G, protocol=pickle.HIGHEST_PROTOCOL))
    log.info("[%.0fs] red descargada", time.time() - t0)

    G = procesamiento.preparar_grafo(G, consolidar_tol_m=a.consolidar)
    log.info("[%.0fs] grafo limpio", time.time() - t0)

    areas = procesamiento.limpiar_areas_verdes(descarga.descargar_features(poly, config.TAGS_AREAS_VERDES))
    poi = procesamiento.limpiar_poi(descarga.descargar_features(poly, config.TAGS_POI))
    log.info("[%.0fs] %d áreas verdes (%d consolidadas), %d POIs", time.time() - t0,
             len(areas), int(areas["consolidado"].sum()) if len(areas) else 0, len(poi))

    aristas, nodos = procesamiento.atributos_aristas(G, areas, poi, comunas)
    procesamiento.volcar_atributos_en_grafo(G, aristas, nodos)
    log.info("[%.0fs] atributos calculados", time.time() - t0)

    escribir_salidas(a.salida, G, aristas, nodos, areas, poi, comunas, poly)
    log.info("Listo en %.1f min -> %s", (time.time() - t0) / 60, a.salida / "grafo_piloto.gpkg")


def escribir_salidas(salida: Path, G, aristas, nodos, areas, poi, comunas, poly) -> dict:
    gpkg = salida / "grafo_piloto.gpkg"
    if gpkg.exists():
        gpkg.unlink()
    aristas.to_file(gpkg, layer="aristas", driver="GPKG")
    nodos.to_file(gpkg, layer="nodos", driver="GPKG")
    areas.to_file(gpkg, layer="areas_verdes", driver="GPKG")
    poi.to_file(gpkg, layer="poi", driver="GPKG")
    comunas.to_crs(config.CRS_METRICO).to_file(gpkg, layer="comunas", driver="GPKG")
    gpd.GeoDataFrame({"nombre": ["area_estudio"]}, geometry=[poly], crs=config.CRS_GEO) \
        .to_crs(config.CRS_METRICO).to_file(gpkg, layer="area_estudio", driver="GPKG")
    (salida / "grafo_piloto.pkl").write_bytes(pickle.dumps(G, protocol=pickle.HIGHEST_PROTOCOL))

    resumen = {
        "crs": config.CRS_METRICO,
        "comunas": sorted(comunas["comuna"].tolist()),
        "nodos": G.number_of_nodes(),
        "aristas": G.number_of_edges(),
        "km_red": round(float(aristas["longitud_m"].sum()) / 1000, 1),
        "areas_verdes": len(areas),
        "parques_consolidados": int(areas["consolidado"].sum()) if len(areas) else 0,
        "nodos_terminal_parque": int(nodos["parque_av_id"].notna().sum()),
        "poi_por_categoria": poi["categoria"].value_counts().to_dict(),
        "aristas_por_comuna": aristas["comuna"].value_counts(dropna=False).to_dict(),
        "pct_aristas_con_uso_social": round(100 * float((aristas["u_social"] > 0).mean()), 1),
        "pct_ancho_vereda_osm": round(100 * float((aristas["ancho_fuente"] == "osm").mean()), 1),
    }
    (salida / "resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return resumen


def cargar_grafo(ruta: str | Path = "salida/grafo_piloto.pkl"):
    """Atajo para los bloques siguientes: carga el grafo con atributos en ~segundos."""
    return pickle.loads(Path(ruta).read_bytes())


if __name__ == "__main__":
    main()
