"""Aves y abejas registradas en el Gran Santiago, desde GBIF (sin captura en terreno).

Uso: python fauna_gbif.py      (unos 5 minutos; se corre de nuevo para actualizar)

GBIF reúne observaciones de eBird, iNaturalist, museos y universidades. Se usan registros con coordenadas,
sin problemas geoespaciales marcados, desde AÑO_DESDE.
- Aves (clase Aves): son cientos de miles, así que se cuentan por barrio (H3 res 7) con los facetas de GBIF:
  registros, especies distintas y las 5 especies más registradas.
- Abejas (familias de Anthophila presentes en Chile): son pocos miles, así que se baja cada registro. Se cuentan
  por barrio, no por cuadra: muchas ubicaciones tienen un margen de cientos de metros (se descartan las de más de
  MAX_INCERTIDUMBRE_M). Las exóticas (abeja de miel y abejorro europeo, que desplaza a los nativos) van aparte.
Escribe:
  data/fauna_h3.parquet         una fila por barrio (ver CONTRATO.md)
  web/public/data/fauna.json    lo que dibuja el mapa: aves y abejas por barrio
Un registro dice que alguien vio la especie ahí; no haber registro no significa que no esté (hay más
observadores en parques y barrios acomodados). Cita: GBIF.org, búsqueda de ocurrencias, consultada en la fecha
de `consultado`.
"""
import json
import time
from pathlib import Path

import h3
import pandas as pd
import requests

import interpolar
import vivo

API = "https://api.gbif.org/v1"
AÑO_DESDE = 2015
AVES = 212
FAMILIAS_ABEJAS = {"Apidae": 4334, "Megachilidae": 7911, "Halictidae": 7908, "Andrenidae": 7901, "Colletidae": 7905}
BASE = {"hasCoordinate": "true", "hasGeospatialIssue": "false", "occurrenceStatus": "PRESENT",
        "year": f"{AÑO_DESDE},2030"}
EXOTICAS = {"Apis mellifera", "Bombus terrestris"}
MAX_INCERTIDUMBRE_M = 1000
SALIDA = vivo.DATA / "fauna_h3.parquet"
WEB = Path("web/public/data/fauna.json")
sesion = requests.Session()
sesion.headers["User-Agent"] = "VerdeH3 (hackathon)"


def pedir(ruta, **params):
    for intento in range(4):
        try:
            r = sesion.get(f"{API}/{ruta}", params=params, timeout=60)
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            if intento == 3:
                raise
            time.sleep(2 ** intento)


def wkt(celda):
    """Hexágono H3 → POLYGON en WKT (lon lat, antihorario, como pide GBIF)."""
    pts = [(lon, lat) for lat, lon in h3.cell_to_boundary(celda)]
    return "POLYGON((" + ", ".join(f"{x:.6f} {y:.6f}" for x, y in pts + pts[:1]) + "))"


def aves_por_barrio(barrios):
    filas, claves = [], set()
    for i, b in enumerate(barrios, 1):
        r = pedir("occurrence/search", geometry=wkt(b), taxonKey=AVES, facet="speciesKey", facetLimit=1000,
                  limit=0, **BASE)
        cuentas = r["facets"][0]["counts"] if r.get("facets") else []
        top = [c["name"] for c in cuentas[:5]]
        claves.update(top)
        filas.append({"h3_padre": b, "aves_registros": r["count"], "aves_especies": len(cuentas), "_top": top})
        if i % 50 == 0:
            print(f"  aves: {i}/{len(barrios)} barrios")
    nombres = {k: nombre(k) for k in claves}
    for f in filas:
        f["aves_top"] = "; ".join(nombres[k] for k in f.pop("_top"))
    return pd.DataFrame(filas)


def nombre(clave):
    """Nombre común en español si GBIF lo tiene; si no, el científico."""
    sp = pedir(f"species/{clave}")
    comunes = pedir(f"species/{clave}/vernacularNames", limit=50).get("results", [])
    es = [c["vernacularName"].split(",")[0].strip(' "') for c in comunes if c.get("language") == "spa"]
    es = [x for x in es if x]
    return f"{es[0].capitalize()} ({sp['canonicalName']})" if es else sp.get("canonicalName", str(clave))


def abejas(lat, lon):
    """Cada registro de abeja dentro del rectángulo de la grilla."""
    puntos = []
    for familia, clave in FAMILIAS_ABEJAS.items():
        offset = 0
        while True:
            r = pedir("occurrence/search", taxonKey=clave, decimalLatitude=f"{lat[0]},{lat[1]}",
                      decimalLongitude=f"{lon[0]},{lon[1]}", limit=300, offset=offset, **BASE)
            for o in r["results"]:
                if (o.get("coordinateUncertaintyInMeters") or 0) > MAX_INCERTIDUMBRE_M:
                    continue
                puntos.append({"lat": o["decimalLatitude"], "lon": o["decimalLongitude"], "familia": familia,
                               "especie": o.get("species") or o.get("genus") or familia,
                               "fecha": (o.get("eventDate") or "")[:10]})
            offset += 300
            if r["endOfRecords"] or offset >= 100_000:
                break
        print(f"  abejas {familia}: {sum(p['familia'] == familia for p in puntos)}")
    return pd.DataFrame(puntos)


def main():
    grilla = pd.read_parquet(vivo.grilla())
    b = interpolar.barrios(grilla)
    print(f"Aves en {len(b)} barrios…")
    aves = aves_por_barrio(list(b.h3_padre))
    print("Abejas…")
    ab = abejas((grilla.lat.min() - 0.01, grilla.lat.max() + 0.01), (grilla.lon.min() - 0.01, grilla.lon.max() + 0.01))
    ab = ab[[h3.latlng_to_cell(a, o, 9) in set(grilla.h3_index) for a, o in zip(ab.lat, ab.lon)]]
    ab["h3_padre"] = [h3.latlng_to_cell(a, o, interpolar.RES_BARRIO) for a, o in zip(ab.lat, ab.lon)]
    ab["exotica"] = ab.especie.isin(EXOTICAS)
    nat = ab[~ab.exotica]
    por_barrio = nat.groupby("h3_padre").agg(abejas_nativas=("especie", "size"), abejas_especies=("especie", "nunique"),
                                             abejas_top=("especie", lambda s: "; ".join(s.value_counts().index[:3])))
    por_barrio["abejas_exoticas"] = ab[ab.exotica].groupby("h3_padre").size()
    fauna = aves.merge(por_barrio.reset_index(), on="h3_padre", how="left")
    fauna = fauna.fillna({"abejas_nativas": 0, "abejas_especies": 0, "abejas_exoticas": 0, "abejas_top": ""})
    fauna = fauna.astype({"abejas_nativas": int, "abejas_especies": int, "abejas_exoticas": int})
    fauna["consultado"] = pd.Timestamp.now(tz="America/Santiago").strftime("%Y-%m-%d")
    fauna.to_parquet(SALIDA, index=False)

    web = {"consultado": fauna.consultado.iat[0], "desde": AÑO_DESDE,
           "barrios": [{"h": r.h3_padre, "an": int(r.aves_registros), "asp": int(r.aves_especies), "atop": r.aves_top,
                        "bn": int(r.abejas_nativas), "bsp": int(r.abejas_especies), "btop": r.abejas_top,
                        "bx": int(r.abejas_exoticas)}
                       for r in fauna[(fauna.aves_registros > 0) | (fauna.abejas_nativas + fauna.abejas_exoticas > 0)].itertuples()]}
    WEB.parent.mkdir(parents=True, exist_ok=True)
    WEB.write_text(json.dumps(web, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Aves: {int(fauna.aves_registros.sum())} registros en {(fauna.aves_registros > 0).sum()} barrios; "
          f"abejas: {len(nat)} nativas y {int(ab.exotica.sum())} exóticas en {(fauna.abejas_nativas > 0).sum()} barrios → {SALIDA}, {WEB}")


if __name__ == "__main__":
    main()
