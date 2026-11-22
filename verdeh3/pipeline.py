"""Viridis, grilla H3 base: python -m verdeh3.pipeline [opciones]

Genera datos/salida_h3/santiago_h3.parquet (GeoParquet, res 8 y 9 en la misma tabla, columna `res`)
y datos/salida_h3/resumen_h3.json. Cada paso cachea su resultado en datos/cache/; si una fuente falla,
el resto se calcula igual y la columna queda vacía (se avisa en el log y en el resumen).
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

from shapely.geometry import box

from ingesta import descarga as ing_descarga
from ingesta import procesamiento as ing_proc

from . import config, fuentes, grilla

log = logging.getLogger("verdeh3")


def _args():
    p = argparse.ArgumentParser(description="Viridis: base H3 pre-calculada")
    p.add_argument("--comunas", nargs="+", default=config.COMUNAS_PILOTO)
    p.add_argument("--pbf", type=Path, help="Extracto OSM local (.osm.pbf); por defecto baja el de Chile")
    p.add_argument("--poblacion-tif", type=Path, help="Ráster de población local en vez de WorldPop")
    p.add_argument("--omitir", nargs="*", default=[], choices=["osm", "ndvi", "lst", "poblacion"])
    p.add_argument("--salida", type=Path, default=Path("datos/salida_h3"))
    p.add_argument("--cache", type=Path, default=Path("datos/cache"))
    return p.parse_args()


def main():
    a = _args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    a.salida.mkdir(parents=True, exist_ok=True)
    a.cache.mkdir(parents=True, exist_ok=True)
    ing_descarga.configurar_osmnx(a.cache)
    t0 = time.time()
    estado = {}

    comunas = ing_descarga.obtener_comunas(a.comunas, None, a.cache)
    area = comunas.union_all().intersection(box(*config.BBOX_URBANO))
    bbox = tuple(round(v, 5) for v in area.bounds)
    log.info("Área de estudio: %s, bbox %s", ", ".join(comunas["comuna"]), bbox)

    hexs = {r: grilla.construir_grilla(comunas, r, area) for r in config.RESOLUCIONES}

    pasos = {
        "osm": lambda: _paso_osm(a, bbox, hexs),
        "ndvi": lambda: grilla.agregar_raster(hexs, *fuentes.ndvi_sentinel2(bbox, a.cache)[:3], "ndvi",
                                              stats=("mean", "p90")),
        "lst": lambda: grilla.agregar_raster(hexs, *fuentes.lst_landsat(bbox, a.cache)[:3], "lst_c",
                                             stats=("mean", "max")),
        "poblacion": lambda: grilla.agregar_raster(
            hexs, *fuentes.poblacion_worldpop(bbox, a.cache, a.poblacion_tif)[:3], "poblacion", stats=("sum",)),
    }
    for nombre, fn in pasos.items():
        if nombre in a.omitir:
            estado[nombre] = "omitido"
            continue
        t = time.time()
        try:
            fn()
            estado[nombre] = f"ok ({time.time() - t:.0f}s)"
        except Exception as e:  # noqa: BLE001  una fuente caída no bota el resto
            log.exception("Paso %s falló", nombre)
            estado[nombre] = f"error: {e}"
        log.info("[%.0fs] %s: %s", time.time() - t0, nombre, estado[nombre])

    for r, h in hexs.items():  # renombrar columnas de stats a nombres simples
        h.rename(columns={"ndvi_mean": "ndvi", "lst_c_mean": "lst_c", "poblacion_sum": "poblacion"}, inplace=True)
    tabla = grilla.finalizar(hexs)
    ruta = a.salida / "santiago_h3.parquet"
    tabla.to_parquet(ruta, index=False)
    resumen = _resumen(tabla, estado, comunas)
    (a.salida / "resumen_h3.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    log.info("Listo en %.1f min -> %s", (time.time() - t0) / 60, ruta)
    print(json.dumps(resumen, ensure_ascii=False, indent=2, default=str))


def _paso_osm(a, bbox, hexs):
    pbf = a.pbf or fuentes.descargar(config.URL_PBF_CHILE, a.cache / "chile-latest.osm.pbf")
    areas_raw, poi_raw = fuentes.leer_osm(pbf, bbox)
    areas = ing_proc.limpiar_areas_verdes(areas_raw)
    poi = ing_proc.limpiar_poi(poi_raw)
    areas.to_file(a.salida / "capas_osm.gpkg", layer="areas_verdes", driver="GPKG")
    poi.to_file(a.salida / "capas_osm.gpkg", layer="poi", driver="GPKG")
    for h in hexs.values():
        grilla.agregar_areas_verdes(h, areas)
        grilla.agregar_poi(h, poi)


def _resumen(tabla, estado, comunas):
    r = {"fuentes": estado, "comunas": sorted(comunas["comuna"])}
    for res, g in tabla.groupby("res"):
        d = {"hexagonos": len(g), "por_comuna": g["comuna"].value_counts().to_dict()}
        for c in ("ndvi", "lst_c", "pct_area_verde", "poblacion", "dist_metro_m"):
            if c in g:
                d[f"{c}_cobertura_pct"] = round(100 * float(g[c].notna().mean()), 1)
                por_comuna = g.groupby("comuna")[c].agg("sum" if c == "poblacion" else "mean")
                d[f"{c}_por_comuna"] = por_comuna.round(2).to_dict()
        r[f"res_{res}"] = d
    return r


if __name__ == "__main__":
    main()
