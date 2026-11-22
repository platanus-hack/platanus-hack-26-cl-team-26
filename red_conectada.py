"""Santiago conectado: la red de corredores sobre todo el Gran Santiago, de 0 a KM_MAX km, para cada «para quién».

Uso: python red_conectada.py      (un par de minutos; se corre de nuevo si cambian la grilla o el optimizador)

Para cada combinación de especies corre una vez el mismo cálculo que «Planificar» con todo Santiago elegido y KM_MAX
km (optimizer.solve_corridor para personas, ecologia.resolver_corredor_por_especies para aves y abejas), sin el aire
ni la vulnerabilidad (PESOS_RED), como las cifras del pitch. La red de cada presupuesto menor son los primeros tramos
de esa, en el orden en que el optimizador los suma: así la red crece sin cambiar de lugar y cada paso contiene al anterior. Escribe web/public/data/red.json, que la sección «Santiago conectado» de la
página recorre con un control deslizante sin volver a calcular nada.

Cifras por presupuesto (todas medidas, salvo los árboles):
- islas: islas verdes distintas que toca la red. Una isla es un grupo de cuadras de parque contiguas (cerro o parque).
- personas: habitantes del Censo en las cuadras de la red y en las vecinas (a una cuadra, unos 300 m).
- barrios_aves: barrios (H3 res 7) que cruza la red con aves registradas en GBIF; aves_max: especies del más rico.
- abejas: registros de abejas nativas (GBIF) en esos barrios; mini: mini islas floridas para abejas.
- arboles: SUPUESTO de un árbol cada METROS_POR_ARBOL metros de corredor (largo_km). No es una medición.
- habitat_ha: hábitat unido. Islas y corredor forman grupos de cuadras verdes que se tocan (las abejas saltan una
  cuadra entre mini islas); se suman las hectáreas de los grupos que juntan dos o más islas, y habitat_islas cuenta
  cuántas islas quedaron así unidas. Sin red, ninguna isla está unida a otra: 0.
- verde_300m: personas a una cuadra (unos 300 m, la distancia que recomienda la OMS Europa, 2016) de una isla o del
  corredor plantado; verde_300m_hoy: lo mismo solo con las islas de hoy.
"""
import json
import math
import sys
from pathlib import Path

import h3
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ecologia import resolver_corredor_por_especies  # noqa: E402
from optimizer import solve_corridor  # noqa: E402
from terreno.servidor import sin_islas  # noqa: E402

GRILLA = Path("data/santiago_h3_gs.parquet")
FAUNA = Path("data/fauna_h3.parquet")
SALIDA = Path("web/public/data/red.json")
KM_MAX, PASO_KM = 100, 5
METROS_POR_ARBOL = 8
COMBINACIONES = {"humanos": ("humanos",), "aves": ("aves",), "abejas": ("abejas",),
                 "todas": ("humanos", "aves", "abejas")}
# Nombres de las islas grandes (los mismos de la página); las demás se cuentan sin nombre.
NOMBRES = [("Cerro San Cristóbal", -33.422, -70.632), ("Cerro Renca", -33.392, -70.713),
           ("Cerro Santa Lucía", -33.4405, -70.6436), ("Parque O'Higgins", -33.4645, -70.66),
           ("Quinta Normal", -33.441, -70.682), ("Cerro Blanco", -33.4195, -70.6445)]


def islas_verdes(df):
    """Cuadra de parque → número de isla (grupos de cuadras de parque contiguas) y el nombre de cada isla."""
    parque = set(df.loc[df.es_parque, "h3_index"])
    isla, n = {}, 0
    for h in parque:
        if h in isla:
            continue
        isla[h], pila = n, [h]
        while pila:
            for v in h3.grid_disk(pila.pop(), 1):
                if v in parque and v not in isla:
                    isla[v] = n
                    pila.append(v)
        n += 1
    nombre = {}
    for txt, lat, lon in NOMBRES:
        cerca = h3.grid_disk(h3.latlng_to_cell(lat, lon, 9), 3)
        ids = [isla[c] for c in cerca if c in isla]
        if ids:
            nombre.setdefault(max(set(ids), key=ids.count), txt)
    return isla, nombre


PASO = math.sqrt(3) * h3.average_hexagon_edge_length(9, unit="km")
HA_CUADRA = h3.average_hexagon_area(9, unit="km^2") * 100   # largo de una cuadra del corredor
# Pesos de la red fija: calor, árboles y personas, sin la vulnerabilidad, como las cifras del pitch. Para sumarla,
# usa optimizer.PESOS (los de «Planificar») y vuelve a correr esto: cambian las islas, personas y hectáreas.
PESOS_RED = {"w_calor": 0.4, "w_arbol": 0.4, "w_personas": 0.2, "w_vuln": 0.0}


def red_completa(df, especies):
    """(tramos en el orden en que se sumaron, mini islas, ¿se planta todo el tramo?) con KM_MAX km."""
    if especies == ("humanos",):
        r = solve_corridor(df, KM_MAX, **PESOS_RED)
        return r["tramos"], [], True
    r = resolver_corredor_por_especies(df, especies, budget_km=KM_MAX, **PESOS_RED)
    return r["tramos"], r["hexes_checkpoints"], especies != ("abejas",)


def hasta(tramos, mini, continuo, km):
    """Los primeros tramos cuyo largo plantado cabe en km: (cuadras del corredor, mini islas, largo en km).
    Con solo abejas se plantan las mini islas y el tramo es la ruta entre ellas."""
    hexes, mi = [], []
    for t in tramos:
        nuevos = [h for h in t if h not in set(hexes)]
        nuevas_mini = [h for h in nuevos if h in mini]
        plantado = len(hexes) + len(nuevos) if continuo else len(mi) + len(nuevas_mini)
        if plantado * PASO > km + 1e-9:
            break
        hexes += nuevos
        mi += nuevas_mini
    return hexes, mi, (len(hexes) if continuo else len(mi)) * PASO


def habitat_unido(verde, isla, salto=1):
    """(hectáreas, islas) de los grupos de cuadras verdes que se tocan (o a `salto` cuadras, para abejas) y juntan
    dos o más islas."""
    visto, ha, islas = set(), 0.0, 0
    for h in verde:
        if h in visto:
            continue
        grupo, pila = {h}, [h]
        visto.add(h)
        while pila:
            for v in h3.grid_disk(pila.pop(), salto):
                if v in verde and v not in visto:
                    visto.add(v)
                    grupo.add(v)
                    pila.append(v)
        n_islas = len({isla[g] for g in grupo if g in isla})
        if n_islas >= 2:
            ha += len(grupo) * HA_CUADRA
            islas += n_islas
    return round(ha), islas


def cerca_del_verde(verde, pob):
    """Personas en las cuadras verdes y en las vecinas (a unos 300 m)."""
    return int(sum(pob.get(v, 0) for v in {v for h in verde for v in h3.grid_disk(h, 1)}))


def cifras(hexes, mini, largo, continuo, km, pob, isla, nombre, fauna):
    red = set(hexes) | set(mini)
    toca = {isla[v] for h in red for v in h3.grid_disk(h, 1) if v in isla}
    plantado = red if continuo else set(mini)   # con solo abejas, la gente cerca de las mini islas
    cerca = {v for h in plantado for v in h3.grid_disk(h, 1)}
    barrios = {h3.cell_to_parent(h, 7) for h in red}
    f = fauna[fauna.h3_padre.isin(barrios)]
    con_aves = f[f.aves_registros > 0]
    return {
        "km": km, "hexes": sorted(hexes), "mini": sorted(mini),
        "islas": len(toca), "nombres": sorted(nombre[i] for i in toca if i in nombre),
        "personas": int(sum(pob.get(h, 0) for h in cerca)),
        "barrios_aves": int(len(con_aves)), "aves_max": int(con_aves.aves_especies.max()) if len(con_aves) else 0,
        "abejas": int(f.abejas_nativas.sum()), "largo_km": round(largo, 2), "arboles": int(round(largo * 1000 / METROS_POR_ARBOL)),
        **dict(zip(("habitat_ha", "habitat_islas"), habitat_unido(set(isla) | plantado, isla, 1 if continuo else 2))),
        "verde_300m": cerca_del_verde(set(isla) | plantado, pob),
    }


def main():
    df = sin_islas(pd.read_parquet(GRILLA)).reset_index(drop=True)
    pob = dict(zip(df.h3_index, df.poblacion))
    isla, nombre = islas_verdes(df)
    fauna = pd.read_parquet(FAUNA)
    salida = {"km_max": KM_MAX, "paso_km": PASO_KM, "metros_por_arbol": METROS_POR_ARBOL,
              "islas_total": len(set(isla.values())), "personas_total": int(df.poblacion.sum()),
              "verde_300m_hoy": cerca_del_verde(set(isla), pob), "red": {}}
    for clave, especies in COMBINACIONES.items():
        tramos, mini, continuo = red_completa(df, especies)
        filas = []
        for km in range(0, KM_MAX + 1, PASO_KM):
            hexes, mi, largo = hasta(tramos, set(mini), continuo, km)
            filas.append(cifras(hexes, mi, largo, continuo, km, pob, isla, nombre, fauna))
        salida["red"][clave] = filas
        u = filas[-1]
        print(f"{clave}: {KM_MAX} km → {u['islas']} islas, {u['personas']:,} personas, {len(u['mini'])} mini islas, "
              f"hábitat unido {u['habitat_ha']} ha ({u['habitat_islas']} islas), {u['verde_300m']:,} a 300 m del verde")
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(salida, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{SALIDA} ({SALIDA.stat().st_size // 1024} KB); {salida['islas_total']} islas verdes en la grilla; hoy: "
          f"{salida['verde_300m_hoy']:,} de {salida['personas_total']:,} personas a 300 m del verde")


if __name__ == "__main__":
    main()
