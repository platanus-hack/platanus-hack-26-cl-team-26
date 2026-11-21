"""Prueba offline de VerdeH3 (grilla, áreas verdes, POIs, rásters y lectura OSM).

Uso: python -m tests.test_h3_sintetico
"""
import tempfile
import time
from pathlib import Path

import geopandas as gpd
import h3
import numpy as np
import rasterio
from shapely.geometry import box

from ingesta import procesamiento as ing_proc
from verdeh3 import config, fuentes, grilla

OSM_XML = """<?xml version='1.0' encoding='UTF-8'?>
<osm version="0.6" generator="test">
  <node id="1" lat="-33.430" lon="-70.610"><tag k="amenity" v="school"/><tag k="name" v="Liceo"/></node>
  <node id="2" lat="-33.432" lon="-70.605"><tag k="highway" v="bus_stop"/></node>
  <node id="3" lat="-33.428" lon="-70.600"><tag k="railway" v="subway_entrance"/></node>
  <node id="4" lat="-33.433" lon="-70.598"><tag k="healthcare" v="clinic"/><tag k="amenity" v="clinic"/></node>
  <node id="10" lat="-33.420" lon="-70.620"/><node id="11" lat="-33.420" lon="-70.610"/>
  <node id="12" lat="-33.425" lon="-70.610"/><node id="13" lat="-33.425" lon="-70.620"/>
  <way id="100"><nd ref="10"/><nd ref="11"/><nd ref="12"/><nd ref="13"/><nd ref="10"/>
    <tag k="leisure" v="park"/><tag k="name" v="Parque Test"/></way>
</osm>
"""


def main():
    t0 = time.time()
    comunas = gpd.GeoDataFrame({"comuna": ["Oeste", "Este"]},
                               geometry=[box(-70.64, -33.45, -70.61, -33.41), box(-70.61, -33.45, -70.58, -33.41)],
                               crs="EPSG:4326")
    area = comunas.union_all()
    bbox = area.bounds
    hexs = {r: grilla.construir_grilla(comunas, r, area) for r in config.RESOLUCIONES}
    assert len(hexs[9]) > 5 * len(hexs[8]) > 0
    assert hexs[9]["comuna"].notna().all() and set(hexs[9]["comuna"]) == {"Oeste", "Este"}
    assert set(hexs[9]["h3_r8"]) <= set(hexs[8]["h3"])
    assert abs(hexs[9]["area_m2"].median() / 1e4 - 10.5) < 1.5, hexs[9]["area_m2"].median()

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "t.osm").write_text(OSM_XML)
        areas_raw, poi_raw = fuentes.leer_osm(d / "t.osm", bbox)
        assert len(areas_raw) == 1 and len(poi_raw) == 4, (len(areas_raw), len(poi_raw))
        areas = ing_proc.limpiar_areas_verdes(areas_raw)
        poi = ing_proc.limpiar_poi(poi_raw)
        assert areas["consolidado"].all()
        assert set(poi["categoria"]) == {"educacion", "paradero", "metro", "salud"}, set(poi["categoria"])
        for h in hexs.values():
            grilla.agregar_areas_verdes(h, areas)
            grilla.agregar_poi(h, poi)
        parque_m2 = areas["area_m2"].sum()
        for r, h in hexs.items():
            assert abs(h["area_verde_m2"].sum() - parque_m2) / parque_m2 < 0.01, (r, h["area_verde_m2"].sum(), parque_m2)
            assert (h["dist_parque_m"].fillna(-1) >= 0).all()
            celda_liceo = h3.latlng_to_cell(-33.430, -70.610, r)
            assert h.loc[h["h3"] == celda_liceo, "n_educacion"].iloc[0] == 1

        # Ráster sintético en UTM 19S: NDVI que crece hacia el este y población 10 hab/píxel.
        from pyproj import Transformer
        x0, y0 = Transformer.from_crs(4326, 32719, always_xy=True).transform(bbox[0], bbox[3])
        x1, y1 = Transformer.from_crs(4326, 32719, always_xy=True).transform(bbox[2], bbox[1])
        ancho, alto = int((x1 - x0) / 20) + 1, int((y0 - y1) / 20) + 1
        t = rasterio.transform.from_origin(x0, y0, 20, 20)
        ndvi = np.tile(np.linspace(0, 0.8, ancho), (alto, 1))
        ndvi[:5, :5] = np.nan
        grilla.agregar_raster(hexs, ndvi, t, "EPSG:32719", "ndvi", stats=("mean", "p90"))
        pob = np.full((alto, ancho), 10.0)
        grilla.agregar_raster(hexs, pob, t, "EPSG:32719", "poblacion", stats=("sum",))
        for h in hexs.values():
            h.rename(columns={"ndvi_mean": "ndvi", "poblacion_sum": "poblacion"}, inplace=True)
        h9 = hexs[9]
        assert h9.loc[h9["frac_en_estudio"] > 0.3, "ndvi"].between(0, 0.8).all()  # bordes mínimos pueden quedar sin píxel
        este, oeste = h9[h9["comuna"] == "Este"]["ndvi"].mean(), h9[h9["comuna"] == "Oeste"]["ndvi"].mean()
        assert este > oeste
        # 10 hab cada 400 m² => ~250 hab por hectárea en hexágonos completos
        llenos = h9[h9["frac_en_estudio"] > 0.99]
        dens = (llenos["poblacion"] / (llenos["area_m2"] / 1e4)).median()
        assert 200 < dens < 300, dens

        tabla = grilla.finalizar(hexs)
        tabla.to_parquet(d / "santiago_h3.parquet", index=False)
        leida = gpd.read_parquet(d / "santiago_h3.parquet")
        assert len(leida) == len(hexs[8]) + len(hexs[9]) and leida.crs.to_epsg() == 4326
        assert {"ndvi", "ndvi_p90", "poblacion", "densidad_hab_km2", "pct_area_verde",
                "dist_metro_m", "cerca_paradero"} <= set(leida.columns)
    print(f"OK: res8={len(hexs[8])} hex, res9={len(hexs[9])} hex, columnas={len(leida.columns)} en {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
