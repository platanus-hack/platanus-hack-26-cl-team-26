"""El viaje del picaflor: del Cerro Renca al Cerro San Cristóbal, en línea recta y por un corredor para aves.

Uso: python viaje_picaflor.py      (menos de un minuto; consulta GBIF)

- Línea recta: las cuadras H3 entre el borde de las dos islas que quedan más cerca (h3.grid_path_cells).
- Corredor: el camino de menor costo para aves entre las dos islas (Dijkstra), con la resistencia para aves de
  ecologia.py (copa fácil, pasto abierto y cemento difíciles). Es el mismo criterio del perfil «Aves».
Por cada cuadra se guarda su copa de árboles (copa_modelo_pct) y si es parque. «Sin árboles» es menos de SIN_COPA %
de copa fuera de un parque; el tramo sin árboles más largo es la mayor cantidad de cuadras seguidas así.
Registros del picaflor chico (Sephanoides sephaniodes) desde 2015: en todo el Gran Santiago y en los barrios (H3 res 7)
que cruza cada ruta (GBIF). Escribe web/public/data/viaje.json.
"""
import heapq
import json
import math
import sys
from pathlib import Path

import h3
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ecologia import calcular_resistencia_ecologica  # noqa: E402
from fauna_gbif import AÑO_DESDE, pedir, wkt  # noqa: E402
from red_conectada import islas_verdes  # noqa: E402
from terreno.servidor import sin_islas  # noqa: E402

GRILLA = Path("data/santiago_h3_gs.parquet")
SALIDA = Path("web/public/data/viaje.json")
ORIGEN, DESTINO = "Cerro Renca", "Cerro San Cristóbal"
PICAFLOR = 2476817   # Sephanoides sephaniodes en GBIF
SIN_COPA = 10
PASO = math.sqrt(3) * h3.average_hexagon_edge_length(9, unit="km")


def cerca(a, b):
    """Par de cuadras (una de cada isla) más cercanas entre sí."""
    return min(((x, y) for x in a for y in b), key=lambda p: h3.grid_distance(*p))


def menor_costo(origen, destino, costo):
    """Dijkstra sobre la grilla: entrar a una cuadra cuesta su resistencia; las islas de origen parten en 0."""
    dist = {h: 0.0 for h in origen}
    prev, cola = {}, [(0.0, h) for h in origen]
    heapq.heapify(cola)
    while cola:
        d, h = heapq.heappop(cola)
        if h in destino:
            camino = [h]
            while camino[-1] in prev:
                camino.append(prev[camino[-1]])
            return camino[::-1]
        if d > dist.get(h, math.inf):
            continue
        for v in h3.grid_disk(h, 1):
            if v in costo and d + costo[v] < dist.get(v, math.inf):
                dist[v], prev[v] = d + costo[v], h
                heapq.heappush(cola, (d + costo[v], v))
    raise RuntimeError("no hay camino entre las islas")


def registros(barrios):
    return sum(pedir("occurrence/search", geometry=wkt(b), taxonKey=PICAFLOR, limit=0, hasCoordinate="true",
                     hasGeospatialIssue="false", occurrenceStatus="PRESENT", year=f"{AÑO_DESDE},2030")["count"]
               for b in sorted(barrios))


def ruta(camino, df, origen, destino):
    """Solo el tramo fuera de las dos islas (el picaflor ya está a salvo dentro de ellas)."""
    tramo = [h for h in camino if h not in origen and h not in destino and h in df.index]
    copa, parque = df.loc[tramo, "copa"], df.loc[tramo, "es_parque"]
    sin = (~parque) & (copa < SIN_COPA)
    racha = mayor = 0
    for s in sin:
        racha = racha + 1 if s else 0
        mayor = max(mayor, racha)
    barrios = {h3.cell_to_parent(h, 7) for h in tramo}
    return {"cuadras": [{"h": h, "copa": round(float(c), 1), "parque": bool(p)} for h, c, p in zip(tramo, copa, parque)],
            "km": round(len(tramo) * PASO, 2), "sin_arboles_max": mayor, "sin_arboles": int(sin.sum()),
            "copa_media": round(float(copa.mean()), 1), "picaflor_barrios": registros(barrios)}


def main():
    df = sin_islas(pd.read_parquet(GRILLA)).reset_index(drop=True)
    df["copa"] = (df["copa_modelo_pct"] if "copa_modelo_pct" in df else df["arbol_pct"]).fillna(0)
    isla, nombre = islas_verdes(df)
    id_de = {v: k for k, v in nombre.items()}
    origen = {h for h, i in isla.items() if i == id_de[ORIGEN]}
    destino = {h for h, i in isla.items() if i == id_de[DESTINO]}
    costo = dict(zip(df.h3_index, calcular_resistencia_ecologica(df, "aves") / 100.0))
    df = df.set_index("h3_index")
    a, b = cerca(origen, destino)
    recta = h3.grid_path_cells(a, b)
    corredor = menor_costo(origen, destino, costo)
    total = pedir("occurrence/search", taxonKey=PICAFLOR, decimalLatitude="-33.65,-33.30",
                  decimalLongitude="-70.85,-70.45", hasCoordinate="true", hasGeospatialIssue="false",
                  occurrenceStatus="PRESENT", year=f"{AÑO_DESDE},2030", limit=0)["count"]
    salida = {"especie": "Sephanoides sephaniodes", "nombre": "picaflor chico", "desde": AÑO_DESDE,
              "registros_santiago": total, "origen": ORIGEN, "destino": DESTINO, "sin_copa_pct": SIN_COPA,
              "recta": ruta(recta, df, origen, destino), "corredor": ruta(corredor, df, origen, destino)}
    SALIDA.write_text(json.dumps(salida, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    for k in ("recta", "corredor"):
        r = salida[k]
        print(f"{k}: {len(r['cuadras'])} cuadras, {r['km']} km, {r['sin_arboles_max']} seguidas sin árboles, "
              f"copa media {r['copa_media']} %, {r['picaflor_barrios']} registros del picaflor en sus barrios")
    print(f"picaflor chico en Santiago: {total} registros desde {AÑO_DESDE} → {SALIDA}")


if __name__ == "__main__":
    main()
