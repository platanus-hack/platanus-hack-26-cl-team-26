"""
Conectividad ecológica: un corredor distinto según para quién se traza.
Diferencia la optimización para:
  - Humanos: Alivio térmico, sombra y densidad poblacional (usa optimizer.solve_corridor).
  - Fauna · Aves: Corredor arbóreo continuo de baja resistencia entre parques/islas verdes.
  - Fauna · Abejas: Mini islas (checkpoints / piedras de paso) para conectar parches separados.
  - Mixto: Equilibrio entre alivio térmico humano y conectividad ecológica.
"""
from __future__ import annotations

import math
import h3
import numpy as np
import pandas as pd

from optimizer import _dijkstra, _norm, _red_continua, _tramos, solve_corridor, urgencia

PERFILES = {
    "humanos": "Humanos (Alivio térmico y sombra)",
    "fauna_aves": "Animales: Aves (Corredor arbóreo continuo)",
    "fauna_abejas": "Animales: Abejas y Polinizadores (Mini islas / Checkpoints)",
    "mixto": "Mixto (Humanos + Fauna)",
}


def calcular_resistencia_ecologica(df: pd.DataFrame, gremio: str = "aves") -> pd.Series:
    """
    Calcula superficie de resistencia (1 = hábitat ideal, 100 = barrera)
    usando las coberturas reales del parquet: copa/árboles, pasto y construido.
    """
    col_arb = "copa_modelo_pct" if "copa_modelo_pct" in df.columns else "arbol_pct"
    arb = df[col_arb].fillna(0).clip(0, 100) / 100.0
    pas = df["pasto_pct"].fillna(0).clip(0, 100) / 100.0
    con = df["construido_pct"].fillna(0).clip(0, 100) / 100.0
    otros = (1.0 - (arb + pas + con)).clip(0, 1)

    if gremio == "abejas":
        # Abejas: pasto con flores = hábitat (1), árboles = recurso (5), construido = barrera (60)
        res = arb * 5.0 + pas * 1.0 + con * 60.0 + otros * 40.0
    else:
        # Aves de bosque: árboles = hábitat (1), pasto = abierto difícil (60), construido = intermedio (40)
        res = arb * 1.0 + pas * 60.0 + con * 40.0 + otros * 50.0

    # Los parques consolidados tienen resistencia mínima
    res = res.where(~df["es_parque"], 1.0)
    return res.clip(1.0, 100.0).rename("resistencia")


def resolver_corredor_por_perfil(
    df: pd.DataFrame,
    perfil: str = "humanos",
    budget_km: float = 3.0,
    w_calor: float = 0.35,
    w_arbol: float = 0.35,
    w_personas: float = 0.2,
    live: pd.DataFrame | None = None,
    salto_checkpoint: int = 2,
    w_vuln: float = 0.1,
) -> dict:
    """
    Ejecuta la optimización según el perfil seleccionado (Humanos, Aves, Abejas o Mixto).
    Retorna un diccionario uniforme con hexes_corredor, hexes_checkpoints, tramos,
    score_mapa (0..1 para colorear), y métricas de impacto.
    """
    if perfil == "humanos":
        res = solve_corridor(
            df,
            budget_km=budget_km,
            w_calor=w_calor,
            w_arbol=w_arbol,
            w_personas=w_personas,
            live=live,
            w_vuln=w_vuln,
        )
        return {
            "perfil": perfil,
            "hexes_corredor": res["hexes"],
            "hexes_checkpoints": [],
            "tramos": res["tramos"],
            "length_km": res["length_km"],
            "score_mapa": res["urgencia"],
            "urgencia_cubierta": res["urgencia_cubierta"],
            "urgencia_azar": res["urgencia_azar"],
            "personas_cubiertas": res["personas_cubiertas"],
            "personas_azar": res["personas_azar"],
            "parques_conectados": len(res["tramos"]) + 1 if res["tramos"] else 0,
            "resistencia_media": float(calcular_resistencia_ecologica(df, "aves").mean()),
        }

    # Para fauna o mixto construimos el grafo sobre todos los hexágonos disponibles en el filtro
    gremio = "abejas" if perfil == "fauna_abejas" else "aves"
    res_eco = calcular_resistencia_ecologica(df, gremio=gremio)
    u_hum = urgencia(df, w_calor, w_arbol, w_personas, live, w_vuln=w_vuln)  # la vulnerabilidad es solo de personas

    if perfil == "mixto":
        # Equilibrio 50% urgencia humana + 50% necesidad de conectar zonas de alta resistencia ecológica
        res_norm = _norm(res_eco)
        prioridad = (0.5 * u_hum + 0.5 * res_norm).rename("prioridad")
        costo_arr = (res_eco / 100.0) * 0.5 + (1.0 / (0.05 + u_hum)) * 0.5
    else:
        # En fauna pura priorizamos reducir barreras de resistencia entre parques separados
        prioridad = _norm(res_eco).rename("prioridad")
        costo_arr = res_eco / 50.0  # menor costo = más fácil de cruzar para el animal

    hexs = df["h3_index"].tolist()
    parque = df["es_parque"].to_numpy()
    pob = df["poblacion"].to_numpy()
    prio_arr = prioridad.to_numpy()
    costos = np.where(parque, 0.0, costo_arr.to_numpy())

    idx = {h: i for i, h in enumerate(hexs)}
    vec = [[idx[v] for v in h3.grid_disk(h, 1) if v != h and v in idx] for h in hexs]

    dist, etiq, prev = _dijkstra(vec, costos, parque)
    tramos = _tramos(vec, dist, etiq, prev, parque, prio_arr)
    paso = math.sqrt(3) * h3.average_hexagon_edge_length(9, unit="km")  # ~0.35 km

    if perfil == "fauna_abejas":
        # Diseño B (Piedras de paso / Mini islas): cada tramo se interviene plantando 1 de cada `salto_checkpoint` hexágonos
        # Esto permite estirar el presupuesto para conectar MÁS parques separados mediante checkpoints
        n_max_islas = max(2, int(round(budget_km / paso)))
        checkpoints_idx = []
        tramos_sel = []
        usados = set()
        parques_cubiertos = set()

        for a, b, cam, um in tramos:
            # Elegir puntos estratégicos (checkpoints) dentro del tramo para romper desiertos de cemento
            pts = [cam[i] for i in range(0, len(cam), salto_checkpoint)]
            if len(cam) > 1 and cam[-1] not in pts:
                pts.append(cam[-1])
            nuevos_pts = [p for p in pts if p not in usados]
            if not nuevos_pts:
                continue
            if len(checkpoints_idx) + len(nuevos_pts) > n_max_islas:
                continue
            checkpoints_idx.extend(nuevos_pts)
            usados.update(nuevos_pts)
            tramos_sel.append([hexs[i] for i in cam])
            parques_cubiertos.update((a, b))

        hexes_cp = [hexs[i] for i in checkpoints_idx]
        # También devolvemos los hexágonos de la ruta de vuelo completa entre checkpoints
        ruta_completa = sorted({h for t in tramos_sel for h in t})
        res_cp = float(res_eco.iloc[checkpoints_idx].mean()) if checkpoints_idx else float(res_eco.mean())
        return {
            "perfil": perfil,
            "hexes_corredor": ruta_completa,
            "hexes_checkpoints": hexes_cp,
            "tramos": tramos_sel,
            "length_km": len(hexes_cp) * paso,
            "score_mapa": prioridad,
            "urgencia_cubierta": float(u_hum.iloc[checkpoints_idx].mean()) if checkpoints_idx else 0.0,
            "urgencia_azar": float(u_hum.mean()),
            "personas_cubiertas": int(pob[checkpoints_idx].sum()) if checkpoints_idx else 0,
            "personas_azar": 0,
            "parques_conectados": len(parques_cubiertos),
            "resistencia_media": res_cp,
        }

    # Perfil fauna_aves o mixto: corredor continuo parque-tramo-parque
    red = _red_continua(tramos, paso, budget_km)
    sel, usado, parques_cubiertos = [], set(), set()
    tramos_sel = []
    for k in red:
        a, b, cam, _ = tramos[k]
        nuevos = [i for i in cam if i not in usado]
        usado.update(nuevos)
        sel += nuevos
        tramos_sel.append([hexs[i] for i in cam])
        parques_cubiertos.update((a, b))

    # En modo mixto, sugerimos además checkpoints en los puntos de mayor resistencia del corredor
    checkpoints_mixto = []
    if perfil == "mixto" and sel:
        # Marcar los puntos más críticos (cada 3er hexágono o los de mayor resistencia) como mini islas floridas
        checkpoints_mixto = [hexs[sel[i]] for i in range(0, len(sel), 3)]

    return {
        "perfil": perfil,
        "hexes_corredor": [hexs[i] for i in sel],
        "hexes_checkpoints": checkpoints_mixto,
        "tramos": tramos_sel,
        "length_km": len(sel) * paso,
        "score_mapa": prioridad,
        "urgencia_cubierta": float(u_hum.iloc[sel].mean()) if sel else 0.0,
        "urgencia_azar": float(u_hum.mean()),
        "personas_cubiertas": int(pob[sel].sum()) if sel else 0,
        "personas_azar": 0,
        "parques_conectados": len(parques_cubiertos),
        "resistencia_media": float(res_eco.iloc[sel].mean()) if sel else float(res_eco.mean()),
    }


# ---------------------------------------------------------------------------------------------------------------
# Varias especies a la vez. Cada especie aporta su propio criterio, ya llevado a la misma escala 0..1, y los
# elegidos se promedian con el mismo peso:
#   humanos: prioridad = urgencia (calor, falta de árboles y personas);  costo de paso = 0,05 / (0,05 + urgencia)
#   aves:    prioridad = resistencia para aves normalizada (árbol fácil, pasto y cemento difíciles);  costo = resistencia / 100
#   abejas:  prioridad = resistencia para abejas normalizada (pasto con flores fácil, cemento difícil); costo = resistencia / 100
# La forma del resultado también sale de las especies: con humanos o aves hay un corredor continuo (sombra para
# caminar, copa para volar de árbol en árbol); con abejas hay mini islas floridas. Con abejas y otra especie van
# las dos cosas: el corredor y, cada tres cuadras, una mini isla en la más difícil de cruzar para una abeja.
ESPECIES = ("humanos", "aves", "abejas")
PERFIL_DE = {frozenset({"humanos"}): "humanos", frozenset({"aves"}): "fauna_aves", frozenset({"abejas"}): "fauna_abejas"}
ESPECIES_DE = {"humanos": ("humanos",), "fauna_aves": ("aves",), "fauna_abejas": ("abejas",), "mixto": ESPECIES}


def criterio_por_especies(df: pd.DataFrame, especies, w_calor=0.35, w_arbol=0.35, w_personas=0.2, live=None,
                          w_vuln=0.1):
    """(prioridad, costo, urgencia humana, resistencia de abejas) para un conjunto de especies. Prioridad y costo
    son el promedio simple de los de cada especie elegida, todos en 0..1."""
    especies = [e for e in ESPECIES if e in set(especies)]
    if not especies:
        raise ValueError("Elige al menos una especie")
    u_hum = urgencia(df, w_calor, w_arbol, w_personas, live, w_vuln=w_vuln)  # vulnerabilidad: solo la de personas
    res = {g: calcular_resistencia_ecologica(df, g) for g in ("aves", "abejas")}
    prioridades, costos = [], []
    for e in especies:
        if e == "humanos":
            prioridades.append(u_hum)
            costos.append(0.05 / (0.05 + u_hum))
        else:
            prioridades.append(_norm(res[e]))
            costos.append(res[e] / 100.0)
    prioridad = (sum(prioridades) / len(especies)).rename("prioridad")
    costo = (sum(costos) / len(especies)).clip(lower=0.01)
    return prioridad, costo, u_hum, res["abejas"]


def resolver_corredor_por_especies(df: pd.DataFrame, especies, budget_km: float = 3.0, w_calor: float = 0.35,
                                   w_arbol: float = 0.35, w_personas: float = 0.2, live=None, apoyo=None,
                                   w_vuln: float = 0.1) -> dict:
    """Corredor para una o más especies. Mismo formato de salida que resolver_corredor_por_perfil, más `fuera`.

    `apoyo`: cuadras de comunas vecinas (mismas columnas que df, sin repetir). Sus parques sirven de extremo y sus
    cuadras de paso, pero cada tramo debe ir al menos la mitad por df. La prioridad que se devuelve es solo la de df.
    Una sola especie sin apoyo usa el perfil de siempre."""
    elegidas = frozenset(e for e in ESPECIES if e in set(especies))
    hay_apoyo = apoyo is not None and len(apoyo) > 0
    if elegidas in PERFIL_DE and not hay_apoyo:
        r = resolver_corredor_por_perfil(df, PERFIL_DE[elegidas], budget_km, w_calor, w_arbol, w_personas, live,
                                         w_vuln=w_vuln)
        return {**r, "fuera": []}
    prioridad, costo, u_hum, res_abejas = criterio_por_especies(df, elegidas, w_calor, w_arbol, w_personas, live,
                                                                w_vuln)
    propia, nucleo = prioridad, np.ones(len(df), dtype=bool)
    if hay_apoyo:
        # Lo elegido conserva su escala; el apoyo se mide sobre el conjunto (igual que optimizer.solve_corridor).
        junto = pd.concat([df, apoyo])
        pj, cj, uj, rj = criterio_por_especies(junto, elegidas, w_calor, w_arbol, w_personas, live, w_vuln)
        une = lambda a, b: pd.concat([a, b.loc[apoyo.index]])
        prioridad, costo, u_hum, res_abejas = une(prioridad, pj), une(costo, cj), une(u_hum, uj), une(res_abejas, rj)
        nucleo = np.r_[nucleo, np.zeros(len(apoyo), dtype=bool)]
        df = junto
    hexs = df["h3_index"].tolist()
    parque, pob = df["es_parque"].to_numpy(), df["poblacion"].to_numpy()
    idx = {h: i for i, h in enumerate(hexs)}
    vec = [[idx[v] for v in h3.grid_disk(h, 1) if v != h and v in idx] for h in hexs]
    dist, etiq, prev = _dijkstra(vec, np.where(parque, 0.0, costo.to_numpy()), parque)
    tramos = _tramos(vec, dist, etiq, prev, parque, prioridad.to_numpy())
    if hay_apoyo:
        tramos = [t for t in tramos if 2 * int(nucleo[t[2]].sum()) >= len(t[2])]
    paso = math.sqrt(3) * h3.average_hexagon_edge_length(9, unit="km")
    sel, usado, parques_cubiertos, tramos_sel, islas = [], set(), set(), [], []
    if elegidas == {"abejas"}:
        # Solo abejas: piedras de paso. De cada tramo se planta una cuadra por medio, hasta agotar el presupuesto.
        n_max = max(2, int(round(budget_km / paso)))
        for a, b, cam, _ in tramos:
            pts = [cam[i] for i in range(0, len(cam), 2)]
            if len(cam) > 1 and cam[-1] not in pts:
                pts.append(cam[-1])
            nuevos = [x for x in pts if x not in usado]
            if not nuevos or len(islas) + len(nuevos) > n_max:
                continue
            islas.extend(nuevos)
            usado.update(nuevos)
            tramos_sel.append([hexs[i] for i in cam])
            parques_cubiertos.update((a, b))
        sel = sorted({idx[h] for t in tramos_sel for h in t})
        largo, medidos = len(islas) * paso, islas
    else:
        for k in _red_continua(tramos, paso, budget_km):
            a, b, cam, _ = tramos[k]
            nuevos = [i for i in cam if i not in usado]
            usado.update(nuevos)
            sel += nuevos
            tramos_sel.append([hexs[i] for i in cam])
            parques_cubiertos.update((a, b))
        # Con abejas: una mini isla cada tres cuadras del corredor, en la de mayor resistencia para ellas.
        if "abejas" in elegidas:
            r = res_abejas.to_numpy()
            islas = [max(sel[k:k + 3], key=lambda i: r[i]) for k in range(0, len(sel), 3)]
        largo, medidos = len(sel) * paso, sel
    return {
        "perfil": "+".join(e for e in ESPECIES if e in elegidas),
        "hexes_corredor": [hexs[i] for i in sel],
        "hexes_checkpoints": [hexs[i] for i in islas],
        "tramos": tramos_sel,
        "length_km": largo,
        "score_mapa": propia,
        "urgencia_cubierta": float(u_hum.iloc[medidos].mean()) if medidos else 0.0,
        "urgencia_azar": float(u_hum[nucleo].mean()),
        "personas_cubiertas": int(pob[medidos].sum()) if medidos else 0,
        "personas_azar": 0,
        "parques_conectados": len(parques_cubiertos),
        "resistencia_media": float(prioridad.iloc[medidos].mean() * 100) if medidos else None,
        "fuera": [hexs[i] for i in sel if not nucleo[i]],   # cuadras del corredor en comunas vecinas
        # Presupuesto mínimo para que salga algo: el tramo más corto (con solo abejas se planta una cuadra por medio).
        "km_min": (min((math.ceil(len(t[2]) / 2) + (len(t[2]) % 2 == 0 and len(t[2]) > 1) if elegidas == {"abejas"} else len(t[2])
                        for t in tramos), default=0) * paso) or None,
    }
