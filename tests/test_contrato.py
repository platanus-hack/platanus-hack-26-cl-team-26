"""Verifica el contrato v3 (CONTRATO.md): columnas, tipos, rangos y el corredor.

Uso: python -m tests.test_contrato
"""
import json
import time
from pathlib import Path

import h3
import pandas as pd

from verdeh3.contrato import TIPOS
from optimizer import solve_corridor

DATA = Path("data")
CLAVES = {"hexes", "length_km", "urgencia_cubierta", "urgencia_azar", "personas_cubiertas"}


def revisar_parquet(ruta: Path):
    assert ruta.stat().st_size < 5e6, f"{ruta} pesa más de 5 MB"
    df = pd.read_parquet(ruta)
    for col, tipo in TIPOS.items():
        assert col in df, f"{ruta}: falta {col}"
        if tipo == "str":
            assert pd.api.types.is_string_dtype(df[col]), f"{ruta}: {col} no es str"
        else:
            assert str(df[col].dtype) == tipo, f"{ruta}: {col} es {df[col].dtype}, no {tipo}"
    assert not df[list(TIPOS)].isna().any().any(), f"{ruta}: hay nulos"
    assert df["h3_index"].is_unique
    assert all(h3.is_valid_cell(h) and h3.get_resolution(h) == 9 for h in df["h3_index"])
    assert (df["h3_padre"] == [h3.cell_to_parent(h, 7) for h in df["h3_index"]]).all()
    assert df["ndvi"].between(0, 1).all() and df["social"].between(0, 1).all()
    for c in ("copa_modelo_pct", "arbol_pct", "pasto_pct", "construido_pct"):
        assert df[c].between(0, 100).all(), c
    assert (df["poblacion"] >= 0).all()
    if "copa_modelo_pct" in df:
        assert df["copa_modelo_pct"].dropna().between(0, 100).all()
    if "lst_fecha" in df:
        assert pd.to_datetime(df["lst_fecha"]).dt.month.isin([12, 1, 2]).all(), "lst_c debe ser de verano"
    return df


def revisar_corredor(df, km):
    t = time.perf_counter()
    r = solve_corridor(df, km)
    ms = 1000 * (time.perf_counter() - t)
    assert CLAVES <= set(r) and isinstance(r["personas_cubiertas"], int)
    assert r["length_km"] <= km + 1e-9, "se pasa del presupuesto"
    parques = set(df.loc[df["es_parque"], "h3_index"])
    assert not set(r["hexes"]) & parques
    assert set(r["hexes"]) == set().union(*r["tramos"]) if r["tramos"] else not r["hexes"]
    # Cada tramo es una cadena de vecinos que va de parque a parque.
    for tramo in r["tramos"]:
        assert all(h3.grid_distance(a, b) == 1 for a, b in zip(tramo, tramo[1:])), "tramo cortado"
        for punta in (tramo[0], tramo[-1]):
            assert set(h3.grid_ring(punta, 1)) & parques, "tramo no llega a un parque"
    # Continuo: hexágonos del corredor más los parques que tocan forman una sola componente.
    nodos = set(r["hexes"]) | {p for h in r["hexes"] for p in h3.grid_ring(h, 1) if p in parques}
    red = set(df["h3_index"])
    nodos |= {p for p in parques if any(q in nodos for q in h3.grid_ring(p, 1))}
    while True:  # los parques son áreas: sumar los hexágonos de parque unidos
        mas = {q for p in nodos & parques for q in h3.grid_ring(p, 1) if q in parques and q in red} - nodos
        if not mas:
            break
        nodos |= mas
    if nodos:
        visto, pila = set(), [next(iter(nodos))]
        while pila:
            u = pila.pop()
            if u in visto:
                continue
            visto.add(u)
            pila += [v for v in h3.grid_ring(u, 1) if v in nodos and v not in visto]
        assert visto == nodos, "el corredor no es continuo"
    return r, ms


def main():
    demo = revisar_parquet(DATA / "santiago_h3.parquet")
    revisar_parquet(DATA / "santiago_h3_mock.parquet")
    gs = revisar_parquet(DATA / "santiago_h3_gs.parquet")
    assert demo["comuna"].nunique() == 2 and gs["comuna"].nunique() == 34

    for km in (1.0, 3.0, 6.0):
        r, ms = revisar_corredor(demo, km)
        assert r["hexes"] and ms < 100, f"{km} km: {ms:.0f} ms"
        assert r["urgencia_cubierta"] > r["urgencia_azar"]
    assert revisar_corredor(demo, 0.1)[0]["hexes"] == []
    r, ms = revisar_corredor(gs, 3.0)
    assert ms < 300, ms

    # El término de árboles usa la copa del modelo: más copa, menos urgencia.
    from optimizer import urgencia
    mas_copa = demo.assign(copa_modelo_pct=demo["copa_modelo_pct"].where(demo.index != demo.index[5], 100.0))
    assert urgencia(mas_copa).iloc[5] < urgencia(demo).iloc[5] or demo["copa_modelo_pct"].iloc[5] >= 30

    # Pesos: se reescalan.
    from optimizer import urgencia
    pd.testing.assert_series_equal(urgencia(demo), urgencia(demo, 3.5, 3.5, 2, w_vuln=1))
    assert demo["vulnerabilidad"].between(0, 1).all() and gs["vulnerabilidad"].between(0, 1).all()

    # En vivo (live de prueba): solo cambian las cuadras de barrios con confianza alta o media, y solo si hay al
    # menos AIRE_MIN_BARRIOS barrios medidos (con menos, unas décimas de grado no reordenan el corredor).
    from optimizer import AIRE_MIN_BARRIOS
    n_ok = AIRE_MIN_BARRIOS
    barrios = demo["h3_padre"].value_counts().index[:n_ok + 2].tolist()
    temps = [26.0, 31.0, 28.0, 33.0, 29.0, 30.0, 32.0, 27.0, 34.0][:n_ok] + [40.0, 35.0]
    live = pd.DataFrame({"h3_padre": barrios, "temp_aire_c": temps,
                         "confianza": (["alta", "media"] * n_ok)[:n_ok] + ["baja", "sin dato"]})
    u0, u1 = urgencia(demo), urgencia(demo, live=live)
    cambia = u1 != u0
    assert cambia.any() and demo.loc[cambia, "h3_padre"].isin(barrios[:n_ok]).all()
    assert (u1 >= 0).all() and (u1 <= 1).all()
    pd.testing.assert_series_equal(urgencia(demo, live=live.iloc[:n_ok - 1]), u0)  # pocos barrios: sin cambio
    pd.testing.assert_series_equal(urgencia(demo, live=live.iloc[n_ok:]), u0)  # baja o sin dato: sin cambio
    t = time.perf_counter()
    assert len(solve_corridor(demo, live=live)["hexes"]) > 0
    assert time.perf_counter() - t < 0.1

    # Modelo de copa: en comunas no vistas debe seguir a Meta mejor que WorldCover.
    m = json.loads((DATA / "modelo_copa.json").read_text())["hexagono_urbano"]
    assert m["modelo_2020_comunas_no_vistas_vs_meta_2019"]["r"] > max(0.85, m["worldcover_2021_vs_meta_2019"]["r"])
    assert abs(m["modelo_2020_comunas_no_vistas_vs_meta_2019"]["sesgo"]) < 1

    print(f"OK test_contrato (demo 3 km: {len(r['hexes'])} hex en 34 comunas, {ms:.0f} ms)")


if __name__ == "__main__":
    main()
