"""Parámetros del pipeline de datos de Viridis."""

# Eje de comunas contrastadas (cambiar con --comunas).
COMUNAS_PILOTO = ["Providencia", "Las Condes", "Estación Central", "Cerro Navia"]

RESOLUCIONES = (8, 9)  # 8: ~461 m de lado (barrio). 9: ~174 m (dos cuadras).

CRS_GEO = "EPSG:4326"
CRS_METRICO = "EPSG:32719"  # UTM 19S

# Recorte a la mancha urbana (Las Condes tiene precordillera). west, south, east, north
BBOX_URBANO = (-70.86, -33.66, -70.45, -33.30)

# Ventana de verano para elegir escenas satelitales (calor máximo, poca nube).
VERANO = "2025-12-01/2026-03-15"
NUBES_MAX_S2 = 5
NUBES_MAX_LANDSAT = 10
STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"

# Factor de decimación al leer Sentinel-2 (2 => 20 m). Suficiente para hexágonos de 10 ha.
DECIMACION_S2 = 2

# OpenStreetMap: extracto completo de Chile (sin límite de uso, a diferencia de Overpass).
URL_PBF_CHILE = "https://download.geofabrik.de/south-america/chile-latest.osm.pbf"

# Población: WorldPop 100 m. Se prueban en orden; también se puede pasar --poblacion-tif.
URLS_WORLDPOP = [
    "https://data.worldpop.org/GIS/Population/Global_2000_2020_Constrained/2020/BSGM/CHL/chl_ppp_2020_constrained.tif",
    "https://data.worldpop.org/GIS/Population/Global_2000_2020_Constrained/2020/maxar_v1/CHL/chl_ppp_2020_UNadj_constrained.tif",
    "https://data.worldpop.org/GIS/Population/Global_2000_2020/2020/CHL/chl_ppp_2020.tif",
]

CATEGORIAS_POI = ["educacion", "salud", "metro", "paradero"]
RADIO_CERCANIA_M = 300
AREA_PARQUE_CONSOLIDADO_M2 = 5_000
