"""Parámetros del área de estudio y de la descarga."""

# CRS métrico de trabajo: UTM 19S. Es el mismo de las escenas Sentinel-2 que
# cubren Santiago, así el Bloque 2 puede muestrear rásters sin reproyectar.
CRS_METRICO = "EPSG:32719"
CRS_GEO = "EPSG:4326"

REGION = "Región Metropolitana de Santiago, Chile"

# Gran Santiago: 32 comunas de la Provincia de Santiago + Puente Alto + San Bernardo.
COMUNAS_GRAN_SANTIAGO = [
    "Cerrillos", "Cerro Navia", "Conchalí", "El Bosque", "Estación Central",
    "Huechuraba", "Independencia", "La Cisterna", "La Florida", "La Granja",
    "La Pintana", "La Reina", "Las Condes", "Lo Barnechea", "Lo Espejo",
    "Lo Prado", "Macul", "Maipú", "Ñuñoa", "Pedro Aguirre Cerda", "Peñalolén",
    "Providencia", "Pudahuel", "Quilicura", "Quinta Normal", "Recoleta",
    "Renca", "San Joaquín", "San Miguel", "San Ramón", "Santiago", "Vitacura",
    "Puente Alto", "San Bernardo",
]

# Comunas periurbanas que se suman con --extendido (conurbación más amplia).
COMUNAS_EXTENDIDAS = ["Padre Hurtado", "Pirque", "Calera de Tango"]

# Consultas Nominatim alternativas cuando el nombre simple es ambiguo.
CONSULTA_ALTERNATIVA = {
    "Santiago": "Santiago, Provincia de Santiago, Región Metropolitana de Santiago, Chile",
}

# Recorte a la mancha urbana (west, south, east, north). Varias comunas (Lo Barnechea,
# Pudahuel, Puente Alto, San Bernardo) tienen mucha superficie rural o cordillerana
# que solo agrega senderos y hace crecer el grafo sin aportar al análisis.
BBOX_URBANO = (-70.86, -33.66, -70.45, -33.30)

# Tamaño máximo de cada consulta a Overpass (m²). OSMnx subdivide el área en
# celdas de este tamaño y guarda cada respuesta en caché: es la descarga por tiles.
MAX_AREA_CONSULTA_M2 = 50 * 1_000_000

# Etiquetas extra de las vías que interesan para veredas y sombra.
TAGS_VIA_EXTRA = [
    "sidewalk", "sidewalk:both", "sidewalk:left", "sidewalk:right",
    "sidewalk:width", "footway", "surface", "lit", "covered", "foot",
]

TAGS_AREAS_VERDES = {
    "leisure": ["park", "garden", "nature_reserve", "playground", "pitch_grass"],
    "landuse": ["recreation_ground", "village_green", "grass", "forest"],
    "place": ["square"],
}

TAGS_POI = {
    "amenity": ["school", "kindergarten", "college", "university",
                "hospital", "clinic", "doctors"],
    "healthcare": True,
    "railway": ["station", "subway_entrance", "halt"],
    "public_transport": ["station", "platform"],
    "highway": ["bus_stop"],
    "social_facility": ["nursing_home"],
}

# Áreas verdes con al menos esta superficie cuentan como "parque consolidado"
# (terminales del motor de corredores del Bloque 3).
AREA_PARQUE_CONSOLIDADO_M2 = 5_000

# Radio del factor de uso social U_e (plan, sección 3).
RADIO_USO_SOCIAL_M = 300

# Distancia para marcar una arista como adyacente a un área verde.
RADIO_ADYACENCIA_PARQUE_M = 15

# Ancho de vereda supuesto (m) por tipo de vía cuando OSM no trae el dato.
# Es un proxy: se reemplaza si el municipio entrega catastro de veredas.
ANCHO_VEREDA_DEFECTO_M = {
    "primary": 3.0, "secondary": 2.5, "tertiary": 2.0, "residential": 1.5,
    "living_street": 1.5, "unclassified": 1.2, "service": 1.0,
    "pedestrian": 6.0, "footway": 2.0, "path": 1.5, "steps": 1.5,
    "cycleway": 2.0, "track": 1.0, "trunk": 2.5,
}
ANCHO_VEREDA_GENERICO_M = 1.5
