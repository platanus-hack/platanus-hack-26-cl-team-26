"""Avenidas y autopistas principales de Santiago desde un extracto OSM (chile-latest.osm.pbf de Geofabrik en cache/) → web/public/data/vias.json.
Uso: python scripts/vias_osm.py web/public/data/vias.json  (necesita geopandas y pyogrio)"""
import json, re, sys
import pyogrio, geopandas as gpd
from shapely.ops import linemerge
from shapely.geometry import MultiLineString

BBOX = (-70.93, -33.70, -70.42, -33.27)
g = pyogrio.read_dataframe("cache/chile-latest.osm.pbf", layer="lines", bbox=BBOX, columns=["name", "highway", "other_tags"],
                           where="highway IN ('motorway','trunk','primary')")
g = g[g["name"].notna()].copy()
g["ref"] = g["other_tags"].fillna("").str.extract(r'"ref"=>"([^"]+)"')[0]
print(len(g), g.highway.value_counts().to_dict())
orden = {"motorway": 0, "trunk": 1, "primary": 2}
def corto(n):
    n = re.sub(r"^(Avenida|Av\.)\s+", "", n.strip())
    n = re.sub(r"^Autopista\s+(?=Vespucio|Costanera|Nororiente|Los Libertadores|del Sol|Acceso)", "", n)
    n = {"Gran Avenida José Miguel Carrera": "Gran Avenida", "Acceso Vial Aeropuerto Arturo Merino Benítez": "Acceso Aeropuerto",
         "Autopista Aeropuerto": "Acceso Aeropuerto", "Pdte. Kennedy Lateral": "Pdte. Kennedy"}.get(n, n)
    n = n.replace("Libertador Bernardo O'Higgins", "Alameda").replace("Presidente Eduardo Frei Montalva", "Pdte. Frei Montalva")
    n = n.replace("Presidente ", "Pdte. ").replace("Circunvalación Américo Vespucio", "Américo Vespucio").replace("General ", "Gral. ")
    return n
g["n"] = g["name"].map(corto)
gm = g.to_crs(32719)
feats = []
for n, grupo in gm.groupby("n"):
    largo = grupo.length.sum()
    clase = min(grupo.highway.map(orden))
    if largo < (2500 if clase < 2 else 4000):
        continue
    m = linemerge(MultiLineString([x for geom in grupo.geometry for x in (geom.geoms if geom.geom_type == "MultiLineString" else [geom])]))
    partes = list(m.geoms) if m.geom_type == "MultiLineString" else [m]
    # calzadas paralelas: quedarse con los tramos largos, para que el nombre no se repita en cada pista
    partes = sorted([p for p in partes if p.length >= 400], key=lambda p: -p.length)
    if not partes:
        continue
    s = gpd.GeoSeries(partes, crs=32719).simplify(12).to_crs(4326)
    coords = [[[round(x, 5), round(y, 5)] for x, y in p.coords] for p in s]
    feats.append({"type": "Feature", "properties": {"n": n, "k": int(clase), "km": round(float(largo) / 1000, 1)},
                  "geometry": {"type": "MultiLineString", "coordinates": coords}})
feats.sort(key=lambda f: (f["properties"]["k"], -f["properties"]["km"]))
out = sys.argv[1]
json.dump({"type": "FeatureCollection", "features": feats}, open(out, "w"), ensure_ascii=False, separators=(",", ":"))
import os
print(len(feats), os.path.getsize(out) // 1024, "KB")
print([f["properties"]["n"] for f in feats])
