# VerdeH3 · respaldo

Base geoespacial en grilla Uber H3 (res 8 y 9) para Providencia, Las Condes, Estación Central y Cerro Navia:
NDVI, temperatura de superficie, áreas verdes, servicios cercanos y población por hexágono.

**Los datos ya calculados están en `datos/`**, así que la demo corre sin internet:

- `datos/salida_h3/santiago_h3.parquet`: tabla final (GeoParquet, EPSG:4326, res 8 y 9 en la columna `res`).
- `datos/salida_h3/capas_osm.gpkg`: áreas verdes y POIs limpios de OSM.
- `datos/salida_h3/resumen_h3.json`: resumen por comuna y estado de cada fuente.
- `datos/cache/`: rásters recortados (`ndvi_s2.tif`, `lst_landsat.tif`, `poblacion_recorte.tif`) y `comunas.gpkg`.

Para regenerarlos:

```bash
pip install -r requirements.txt
python -m verdeh3.pipeline --cache datos/cache --salida datos/salida_h3
```

El extracto OSM de Chile (`chile-latest.osm.pbf`, ~350 MB, Geofabrik) se baja solo la primera vez.

Escenas usadas:

- NDVI: Sentinel-2 `S2B_MSIL2A_20260206T143739_R096_T19HCD` (2026-02-06, 0 % nubes).
- LST: Landsat 8 `LC08_L2SP_233083_20260211_02_T1` (2026-02-11, 0,3 % nubes).

Advertencias:

- Las Condes incluye precordillera: filtra los hexágonos con `poblacion < 50` antes de comparar comunas
  (si no, el % de área verde sube por bosques y reservas).
- Para totales de población por comuna, pondera cada hexágono por `frac_en_estudio`; los hexágonos de borde
  traen su población completa y la suma simple la infla.

Prueba offline: `python -m tests.test_h3_sintetico`.

## Gran Santiago (34 comunas)

Las 32 comunas de la Provincia de Santiago más Puente Alto y San Bernardo, recortadas a `BBOX_URBANO`.
Van aparte de las 4 comunas de arriba, que no cambian:

- `datos/salida_h3_gs/santiago_h3.parquet`: 1.956 hexágonos res 8 y 13.172 res 9, mismas columnas más
  `elev_m`, `precordillera` (≥ 900 m), `baja_poblacion` (< 500 hab/km²) y `comuna_piloto` (las 4 originales).
- `datos/salida_h3_gs/capas_osm.gpkg` y `resumen_h3.json`.
- `datos/cache_gs/`: rásters recortados al área completa, más `elev_cop30.tif` (Copernicus DEM 30 m).

Para regenerarlos (los rásters de caché no llevan el bbox en el nombre, por eso van en otra carpeta):

```bash
python -m verdeh3.mosaico_s2 --cache datos/cache_gs --fecha 2026-02-06   # ninguna tesela S2 cubre sola el área
python -m verdeh3.pipeline --cache datos/cache_gs --salida datos/salida_h3_gs --comunas Cerrillos "Cerro Navia" \
  Conchalí "El Bosque" "Estación Central" Huechuraba Independencia "La Cisterna" "La Florida" "La Granja" \
  "La Pintana" "La Reina" "Las Condes" "Lo Barnechea" "Lo Espejo" "Lo Prado" Macul Maipú Ñuñoa \
  "Pedro Aguirre Cerda" Peñalolén Providencia Pudahuel Quilicura "Quinta Normal" Recoleta Renca \
  "San Joaquín" "San Miguel" "San Ramón" Santiago Vitacura "Puente Alto" "San Bernardo"
python -m verdeh3.marcar_gs --cache datos/cache_gs --salida datos/salida_h3_gs
```

NDVI: mosaico de `S2A_MSIL2A_20260206T144901_R096_T19HCD` y `..._T19HCC` (2026-02-06). LST: la misma escena Landsat.

Advertencias:

- Para sacar el cerro usa `precordillera`; `baja_poblacion` también atrapa parques, aeropuerto e industrias.
- WorldPop 2020 constrained reparte mal la población entre comunas (Maipú 1,58 M, Puente Alto 1,13 M,
  Santiago 135 k; total 7,6 M). Sirve para comparar densidades, no para cifras por comuna.

## Contrato v3 y optimizador (Rol 1)

Ver `CONTRATO.md`. Comunas de la demo: Providencia y Cerro Navia.

```bash
python -m verdeh3.worldcover    # árboles, pasto y construido (ESA WorldCover 2021) en datos/salida_h3_gs
python -m verdeh3.contrato      # data/santiago_h3.parquet, _mock, _gs (34 comunas) y data/cifras_pitch.json
python -m tests.test_contrato
```

`optimizer.solve_corridor(df, budget_km=3.0, w_calor=0.4, w_arbol=0.4, w_personas=0.2, live=None)` devuelve el
corredor continuo entre parques que más urgencia cubre dentro del presupuesto.

# Corredores Verdes · Bloque 1

Ingesta geoespacial del Gran Santiago: `python -m ingesta.pipeline` (ver `ingesta/pipeline.py`).
