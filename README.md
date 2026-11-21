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

# Corredores Verdes · Bloque 1

Ingesta geoespacial del Gran Santiago: `python -m ingesta.pipeline` (ver `ingesta/pipeline.py`).
