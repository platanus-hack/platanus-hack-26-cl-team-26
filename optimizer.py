"""Corredor verde óptimo bajo presupuesto (Rol 1, contrato v3: ver CONTRATO.md).

    from optimizer import solve_corridor
    r = solve_corridor(pd.read_parquet("data/santiago_h3.parquet"), budget_km=3.0)
    r["hexes"], r["length_km"], r["urgencia_cubierta"], r["urgencia_azar"], r["personas_cubiertas"]

Urgencia por hexágono (cada término 0 a 1):
  calor    = 0,6·lst_c_norm + 0,4·vivo_norm   (vivo = temp_aire_c del barrio res 7, confianza alta o media;
             donde no hay dato en vivo, o hay menos de dos barrios con dato, solo lst_c_norm)
  falta    = 1 − copa_norm   (copa_modelo_pct: % de copa de árboles que predice nuestro modelo con
             Sentinel-2 de 2026, ver verdeh3.modelo_copa; sin esa columna, 1 − arbol_pct/100 de WorldCover)
  personas = 0,7·poblacion_norm + 0,3·social
  bio      = biodiversidad_terreno del hexágono (aves oídas o vistas, polinizadores, flores; solo con
             `terreno`, 0 donde no hay datos de terreno)
  U        = (w_calor·calor + w_arbol·falta + w_personas·personas + w_bio·bio) / (suma de los pesos)
  Los pesos se pueden mover libremente: se reescalan para sumar 1 (0,4/0,4/0,2 queda igual).
  w_bio = 0 por omisión (resultado idéntico al de antes). Con w_bio > 0 el corredor prefiere pasar por donde
  el equipo registró fauna: conecta hábitat que ya existe. No detectar fauna no significa que no haya, y un
  hexágono sin visitar vale 0; por eso conviene un peso bajo (el mapa usa 0,1).

Corredor: grafo de vecindad H3 (grid_disk(h, 1)). Entrar a un hexágono cuesta 1/(0,05 + U); los
parques cuestan 0. Un Dijkstra con todos los parques como origen da el camino más barato entre cada
par de parques vecinos (tramos). Se arma una sola red continua parque-tramo-parque, agregando tramos
de mayor urgencia por km mientras quepan en el presupuesto. Se compara con caminatas al azar del
mismo largo que parten junto a un parque. No se informan °C de enfriamiento (sin coeficiente citado).

Terreno (opcional, `terreno=` = data/terreno_h3.parquet, ver CONTRATO.md): donde hay fotos de terreno,
el término falta pasa a ser el promedio entre el déficit satelital (copa_modelo_pct o arbol_pct) y el de
la foto (1 − arbol_pct_terreno/100): la foto de calle complementa al satélite, no lo reemplaza. Además
los hexágonos con viabilidad_terreno < 0,2 que no son parque salen del grafo (verificados como no
plantables). Sin `terreno` el resultado es idéntico al de antes.
"""
from __future__ import annotations

import heapq
import math
import random

import h3
import numpy as np
import pandas as pd

EPS = 0.05
CONFIANZA_OK = ("alta", "media")
# Aire en vivo: entra solo con varios barrios medidos y en escala fija, para que décimas de grado entre pocos
# sensores no reordenen el corredor entero (antes se estiraba a 0..1 el rango que hubiera, aunque fuera de 1 °C).
AIRE_MIN_BARRIOS = 5
AIRE_ESCALA_C = 6.0        # 0..1 cubre ±3 °C alrededor de la mediana de los barrios medidos
AIRE_PESO = 0.3            # parte del término de calor que aporta el aire donde hay dato; el resto es el suelo
MIN_PERSONAS_HEX = 50      # ~500 hab/km²: industria o eriazo; ahí no se planta salvo parques
N_AZAR = 200
SEMILLAS = 20
VIABILIDAD_MIN = 0.2       # bajo esto, un hexágono verificado en terreno no entra al grafo (salvo parques)


def _norm(s: pd.Series) -> pd.Series:
    """Min-max robusto (percentiles 2 y 98) a 0..1."""
    if not len(s):
        return s.astype(float)
    lo, hi = np.nanpercentile(s.astype(float), [2, 98])
    return ((s - lo) / (hi - lo)).clip(0, 1) if hi > lo else s * 0.0


def _terreno(df, terreno):
    """Columnas de terreno alineadas con df (NaN donde no hay captura)."""
    t = terreno.drop_duplicates("h3_index").set_index("h3_index")
    return df["h3_index"].map(t["arbol_pct_terreno"]), df["h3_index"].map(t["viabilidad_terreno"])


def biodiversidad(df, terreno) -> pd.Series:
    """biodiversidad_terreno (0..1) alineada con df; 0 donde no hay datos de terreno."""
    if terreno is None or not len(terreno) or "biodiversidad_terreno" not in terreno:
        return pd.Series(0.0, index=df.index)
    t = terreno.drop_duplicates("h3_index").set_index("h3_index")["biodiversidad_terreno"]
    return df["h3_index"].map(t).fillna(0.0).clip(0, 1)


def urgencia(df, w_calor=0.4, w_arbol=0.4, w_personas=0.2, live=None, terreno=None, w_bio=0.0) -> pd.Series:
    w = (w_calor, w_arbol, w_personas, w_bio)
    if min(w) < 0 or sum(w) <= 0:
        raise ValueError(f"Pesos deben ser >= 0 y no todos 0: {w}")
    calor = _norm(df["lst_c"])
    if live is not None and len(live):
        # live_h3.parquet: una fila por barrio (h3_padre, res 7). Nunca se inventa un valor en vivo.
        ok = live[live["confianza"].isin(CONFIANZA_OK) & live["temp_aire_c"].notna()]
        padre = df["h3_padre"] if "h3_padre" in df else df["h3_index"].map(lambda h: h3.cell_to_parent(h, 7))
        vivo = padre.map(ok.groupby("h3_padre")["temp_aire_c"].last())
        if ok["h3_padre"].nunique() >= AIRE_MIN_BARRIOS:
            aire = (0.5 + (vivo - vivo.median()) / AIRE_ESCALA_C).clip(0, 1)
            calor = ((1 - AIRE_PESO) * calor + AIRE_PESO * aire).where(vivo.notna(), calor)
    if "copa_modelo_pct" in df:  # la copa urbana va de 0 a ~40%: se normaliza como los demás términos
        falta = 1 - _norm(df["copa_modelo_pct"])
    else:
        falta = 1 - df["arbol_pct"].clip(0, 100) / 100
    if terreno is not None and len(terreno):  # foto de calle: promedio de déficits (misma escala 0..1)
        campo, _ = _terreno(df, terreno)
        falta = ((falta + (1 - campo.clip(0, 100) / 100)) / 2).where(campo.notna(), falta)
    personas = 0.7 * _norm(df["poblacion"]) + 0.3 * df["social"].clip(0, 1)
    u = w_calor * calor + w_arbol * falta + w_personas * personas
    if w_bio:
        u = u + w_bio * biodiversidad(df, terreno)
    return (u / sum(w)).rename("urgencia")


def _dijkstra(vec, costo, parque):
    """Desde todos los parques a la vez; parques unidos forman un solo origen (etiqueta)."""
    n = len(vec)
    dist, etiq, prev = np.full(n, np.inf), np.full(n, -1), np.full(n, -1)
    for s in np.flatnonzero(parque):
        if etiq[s] >= 0:
            continue
        etiq[s], pila = s, [s]
        while pila:
            u = pila.pop()
            dist[u] = 0.0
            for v in vec[u]:
                if parque[v] and etiq[v] < 0:
                    etiq[v] = s
                    pila.append(v)
    heap = [(0.0, int(u)) for u in np.flatnonzero(parque)]
    while heap:
        d, u = heapq.heappop(heap)
        if d > dist[u]:
            continue
        for v in vec[u]:
            if d + costo[v] < dist[v]:
                dist[v], etiq[v], prev[v] = d + costo[v], etiq[u], u
                heapq.heappush(heap, (dist[v], v))
    return dist, etiq, prev


def _tramos(vec, dist, etiq, prev, parque, U):
    """Camino más barato entre cada par de parques vecinos: (parque_a, parque_b, hexágonos, U media)."""
    mejor = {}
    for u in range(len(vec)):
        for v in vec[u]:
            if v > u and etiq[u] >= 0 and etiq[v] >= 0 and etiq[u] != etiq[v]:
                par, c = (min(etiq[u], etiq[v]), max(etiq[u], etiq[v])), dist[u] + dist[v]
                if c > 0 and c < mejor.get(par, (np.inf,))[0]:
                    mejor[par] = (c, u, v)

    def cadena(x):
        out = []
        while x >= 0 and not parque[x]:
            out.append(x)
            x = prev[x]
        return out

    tramos = []
    for (a, b), (_, u, v) in mejor.items():
        cam = cadena(u)[::-1] + cadena(v)
        tramos.append((a, b, cam, float(U[cam].mean())))
    return sorted(tramos, key=lambda t: (-t[3], len(t[2])))


def _red_continua(tramos, paso, budget_km):
    """Red de tramos unida por parques, codiciosa por urgencia; prueba SEMILLAS puntos de partida."""
    def crecer(k0):
        elegidos, usado, parques, total = [], set(), set(), 0.0
        cola = [k0]
        while cola:
            k = cola.pop(0)
            a, b, cam, um = tramos[k]
            nuevos = [i for i in cam if i not in usado]
            if not nuevos or (len(usado) + len(nuevos)) * paso > budget_km + 1e-9:
                continue
            elegidos.append(k)
            usado.update(nuevos)
            parques.update((a, b))
            total += um * len(nuevos)
            cola = [j for j, t in enumerate(tramos) if j not in elegidos
                    and ({t[0], t[1]} & parques or usado.intersection(t[2]))]
        return elegidos, total

    redes = [crecer(k) for k in range(min(SEMILLAS, len(tramos)))]
    return max(redes, key=lambda r: r[1])[0] if redes else []


def solve_corridor(df, budget_km=3.0, w_calor=0.4, w_arbol=0.4, w_personas=0.2, live=None,
                   terreno=None, w_bio=0.0, apoyo=None) -> dict:
    """`apoyo`: cuadras de comunas vecinas (mismas columnas que df, sin repetir). Sus parques sirven de extremo y
    sus cuadras de paso, pero cada tramo debe ir en su mayoría por df. La urgencia que se devuelve es solo la de df."""
    U_todo = urgencia(df, w_calor, w_arbol, w_personas, live, terreno, w_bio)
    nucleo = pd.Series(True, index=df.index)
    if apoyo is not None and len(apoyo):
        junto = pd.concat([df, apoyo])
        # La urgencia de lo elegido no cambia al sumar apoyo; la del apoyo se mide sobre el conjunto.
        U_ap = urgencia(junto, w_calor, w_arbol, w_personas, live, terreno, w_bio).loc[apoyo.index]
        nucleo = pd.concat([nucleo, pd.Series(False, index=apoyo.index)])
        U_propia, df, U_todo = U_todo, junto, pd.concat([U_todo, U_ap])
    else:
        U_propia = U_todo
    ok = df["es_parque"] | (df["poblacion"] >= MIN_PERSONAS_HEX)
    verificado = pd.Series(False, index=df.index)
    if terreno is not None and len(terreno):
        _, viab = _terreno(df, terreno)
        con_fotos = terreno["n_capturas"] > 0 if "n_capturas" in terreno else slice(None)
        verificado = df["h3_index"].isin(terreno.loc[con_fotos, "h3_index"])  # solo escuchas no verifica
        ok &= df["es_parque"] | ~(viab < VIABILIDAD_MIN)  # NaN (sin dato de espacio) no excluye
    ok = ok.to_numpy()
    hexs = df["h3_index"][ok].tolist()
    U, parque, pob = U_todo[ok].to_numpy(), df["es_parque"][ok].to_numpy(), df["poblacion"][ok].to_numpy()
    nuc = nucleo[ok].to_numpy()
    idx = {h: i for i, h in enumerate(hexs)}
    vec = [[idx[v] for v in h3.grid_disk(h, 1) if v != h and v in idx] for h in hexs]
    dist, etiq, prev = _dijkstra(vec, np.where(parque, 0.0, 1.0 / (EPS + U)), parque)
    tramos = _tramos(vec, dist, etiq, prev, parque, U)
    if not nuc.all():
        # Con apoyo: los tramos que van al menos la mitad por lo elegido, más los que ya salían sin apoyo
        # (solo por lo elegido y entre sus propios parques), para que activar el apoyo nunca quite opciones.
        tramos = [t for t in tramos if 2 * int(nuc[t[2]].sum()) >= len(t[2])]
        vec_n = [[v for v in vs if nuc[v]] if nuc[i] else [] for i, vs in enumerate(vec)]
        par_n = parque & nuc
        d_n, e_n, p_n = _dijkstra(vec_n, np.where(par_n, 0.0, 1.0 / (EPS + U)), par_n)
        vistos = {frozenset(t[2]) for t in tramos}
        for a, b, cam, um in _tramos(vec_n, d_n, e_n, p_n, par_n, U):
            if frozenset(cam) not in vistos:
                tramos.append((int(etiq[a]), int(etiq[b]), cam, um))  # mismas etiquetas de parque que el resto
        tramos.sort(key=lambda t: (-t[3], len(t[2])))
    paso = math.sqrt(3) * h3.average_hexagon_edge_length(9, unit="km")  # ~0,35 km entre centros

    red = _red_continua(tramos, paso, budget_km)
    sel, largos, usado = [], [], set()
    for k in red:
        nuevos = [i for i in tramos[k][2] if i not in usado]
        usado.update(nuevos)
        sel += nuevos
        largos.append(len(nuevos))

    # Azar: mismas cantidades de hexágonos por tramo, caminatas sin repetir desde junto a un parque.
    rng = random.Random(0)
    inicio = [i for i in range(len(vec)) if nuc[i] and not parque[i] and any(parque[v] for v in vec[i])]
    if not inicio:  # lo elegido no toca ningún parque (el corredor llega a los de comunas vecinas)
        inicio = [i for i in range(len(vec)) if nuc[i] and not parque[i]]
    u_az, p_az = [], []
    for _ in range(N_AZAR if sel and inicio else 0):
        vis = set()
        for k in largos:
            cam = [rng.choice(inicio)]
            while len(cam) < k:
                op = [v for v in vec[cam[-1]] if nuc[v] and not parque[v] and v not in vis and v not in cam]
                if not op:
                    break
                cam.append(rng.choice(op))
            vis.update(cam)
        vis = list(vis)
        u_az.append(U[vis].mean())
        p_az.append(pob[vis].sum())

    return {
        "hexes": [hexs[i] for i in sel],
        "length_km": len(sel) * paso,
        "urgencia_cubierta": float(U[sel].mean()) if sel else 0.0,
        "urgencia_azar": float(np.mean(u_az)) if u_az else 0.0,
        "personas_cubiertas": int(pob[sel].sum()) if sel else 0,
        "personas_azar": int(np.mean(p_az)) if p_az else 0,
        "verificados": int(verificado[ok].to_numpy()[sel].sum()) if sel else 0,
        "tramos": [[hexs[i] for i in tramos[k][2]] for k in red],
        "urgencia": U_propia,
        "fuera": [hexs[i] for i in sel if not nuc[i]],   # cuadras del corredor en comunas vecinas (apoyo)
        # Largo del tramo más corto entre dos parques: el presupuesto mínimo para que salga algún corredor.
        "km_min": min((len(t[2]) for t in tramos), default=0) * paso or None,
    }
