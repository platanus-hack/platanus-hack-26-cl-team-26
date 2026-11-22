"""Genera los parquet del contrato v3 (ver CONTRATO.md) desde la salida de verdeh3.

python -m verdeh3.contrato          # data/santiago_h3.parquet (par de la demo),
                                         # data/santiago_h3_gs.parquet (34 comunas) y data/santiago_h3_mock.parquet

Requiere antes: verdeh3.pipeline, verdeh3.marcar_gs, verdeh3.worldcover y verdeh3.censo sobre datos/salida_h3_gs.
Población: Censo 2024 por manzana (poblacion_censo); si no está, WorldPop (poblacion).
Vulnerabilidad al calor: de los conteos censo_* que agrega verdeh3.censo (ver vulnerabilidad()).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import h3
import numpy as np
import pandas as pd

from optimizer import _norm, solve_corridor

COMUNAS_DEMO = ["Providencia", "Cerro Navia"]
PCT_VERDE_PARQUE = 25   # es_parque: toca parque consolidado (>= 5.000 m²) y >= 25% del hexágono es área verde
RADIO_SOCIAL_M = 1000   # social: promedio de max(0, 1 − distancia/1 km) a colegio, salud, metro y paradero
CATEGORIAS_SOCIAL = ["educacion", "salud", "metro", "paradero"]
TIPOS = {"h3_index": "str", "h3_padre": "str", "comuna": "str", "lat": "float64", "lon": "float64", "lst_c": "float64",
         "ndvi": "float64", "copa_modelo_pct": "float64", "arbol_pct": "float64", "pasto_pct": "float64", "construido_pct": "float64",
         "poblacion": "int64", "social": "float64", "es_parque": "bool", "vulnerabilidad": "float64"}

# Vulnerabilidad al calor (Censo 2024 por manzana, repartido a cada cuadra por verdeh3.censo). Componentes en %:
#   sensibilidad: personas de 60 años o más, de 0 a 5 años y con discapacidad (sobre las personas de la cuadra)
#   capacidad de adaptación baja: viviendas hacinadas e irrecuperables (sobre las viviendas ocupadas) y menos años
#   de escolaridad (promedio de los mayores de 18, ponderado por personas)
# Cada componente se normaliza 0..1 (percentiles 2 y 98) sobre las 34 comunas; vulnerabilidad = promedio de
# sensibilidad y capacidad, cada una el promedio de sus tres componentes. No es ingreso: el Censo no lo pregunta.
MIN_PERSONAS_VULN = 50  # con menos personas los porcentajes de una cuadra son ruido: queda la mediana de la comuna
VULN_PCT = {  # columna: (numerador, denominador) de verdeh3.censo
    "pct_60_mas": ("censo_60_mas", "poblacion_censo"),
    "pct_0_5": ("censo_0_5", "poblacion_censo"),
    "pct_discapacidad": ("censo_discapacidad", "poblacion_censo"),
    "pct_viv_hacinadas": ("censo_viv_hacinadas", "censo_viv_ocupadas"),
    "pct_viv_irrecuperables": ("censo_viv_irrecuperables", "censo_viv_ocupadas"),
}


def vulnerabilidad(t: pd.DataFrame) -> pd.DataFrame:
    """Componentes y vulnerabilidad (0..1) por cuadra, alineados con t. NaN donde hay menos de MIN_PERSONAS_VULN."""
    if not all(c in t for num_den in VULN_PCT.values() for c in num_den):
        print("Aviso: falta correr verdeh3.censo con las variables de vulnerabilidad; vulnerabilidad = 0")
        return pd.DataFrame({"vulnerabilidad": 0.0}, index=t.index)
    ok = t["poblacion_censo"] >= MIN_PERSONAS_VULN
    v = pd.DataFrame(index=t.index)
    for col, (num, den) in VULN_PCT.items():
        v[col] = (100 * t[num] / t[den].where(t[den] > 0)).clip(0, 100).where(ok)
    v["escolaridad"] = (t["censo_escolaridad_x_per"] / t["censo_per_escolaridad"].where(t["censo_per_escolaridad"] > 0)).where(ok)
    sensibilidad = (_norm(v["pct_60_mas"]) + _norm(v["pct_0_5"]) + _norm(v["pct_discapacidad"])) / 3
    adaptacion = (_norm(v["pct_viv_hacinadas"]) + _norm(v["pct_viv_irrecuperables"]) + 1 - _norm(v["escolaridad"])) / 3
    v["vulnerabilidad"] = (sensibilidad + adaptacion) / 2
    return v


def armar(origen: Path, comunas: list[str] | None = None) -> pd.DataFrame:
    t = pd.read_parquet(origen)
    t = t[t["res"] == 9]
    vuln = vulnerabilidad(t)  # sobre las 34 comunas: la escala no depende de qué comunas se exporten
    if comunas:
        t = t[t["comuna"].isin(comunas)]
        vuln = vuln.loc[t.index]
    cerca = [(1 - t[f"dist_{c}_m"].fillna(np.inf) / RADIO_SOCIAL_M).clip(0, 1) for c in CATEGORIAS_SOCIAL]
    df = pd.DataFrame({
        "h3_index": t["h3"], "h3_padre": [h3.cell_to_parent(h, 7) for h in t["h3"]], "comuna": t["comuna"], "lat": t["lat"], "lon": t["lng"],
        "lst_c": t["lst_c"], "ndvi": t["ndvi"].clip(0, 1),
        "copa_modelo_pct": t["copa_modelo_pct"], "arbol_pct": 100 * t["frac_arboles"], "pasto_pct": 100 * t["frac_pasto"],
        "construido_pct": 100 * t["frac_construido"],
        "poblacion": t["poblacion_censo" if "poblacion_censo" in t else "poblacion"].fillna(0).round(),
        "social": sum(cerca) / len(cerca),
        "es_parque": (t["n_parques_consolidados"] > 0) & (t["pct_area_verde"] >= PCT_VERDE_PARQUE),
    }).reset_index(drop=True)
    for c in vuln.columns:  # vulnerabilidad y sus componentes (NaN en cuadras casi vacías: se rellenan abajo)
        df[c] = vuln[c].to_numpy()
    for c in ("lst_fecha", "lst_c_ultima", "lst_fecha_ultima"):  # extras de verdeh3.landsat, para el mapa
        if c in t:
            df[c] = t[c].to_numpy()
    for c in df.columns[df.isna().any()]:  # pocos hexágonos sin píxel válido: mediana de su comuna
        df[c] = df[c].fillna(df.groupby("comuna")[c].transform("median"))
    # Extras de árboles, sin rellenar: NaN donde la fuente no se calculó.
    #   arboles_meta, altura_copa_m, copa_pct_meta: verdeh3.arboles (Meta/WRI, 1 m, imágenes 2019)
    #   arbol_pct_io_<año>: verdeh3.impact (Impact Observatory/Esri, 10 m)
    extras = {"n_arboles": "arboles_meta", "altura_copa_m": "altura_copa_m", "copa_pct": "copa_pct_meta"}
    extras |= {c: c for c in t if c.startswith(("arbol_pct_io_", "copa_modelo_"))}  # verdeh3.modelo_copa
    for origen, destino in extras.items():
        if origen in t:
            df[destino] = t[origen].to_numpy()
    return df.round(4).astype({**TIPOS, **{c: "str" for c in df if c.startswith("lst_fecha")}})


def con_corredor(df: pd.DataFrame, km: float) -> tuple[pd.DataFrame, dict]:
    r = solve_corridor(df, km)
    return df.assign(urgencia=r["urgencia"].round(4), en_corredor=df["h3_index"].isin(r["hexes"])), r


def mock(df: pd.DataFrame, n: int = 30, semilla: int = 0) -> pd.DataFrame:
    """n hexágonos reales y contiguos (alrededor del centro de la primera comuna) con valores inventados."""
    rng = np.random.default_rng(semilla)
    centro = df.loc[df["comuna"] == df["comuna"].iloc[0], ["lat", "lon"]].mean()
    c0 = h3.latlng_to_cell(centro["lat"], centro["lon"], 9)
    celdas = sorted(h3.grid_disk(c0, 3), key=lambda c: (h3.grid_distance(c0, c), c))[:n]
    lat, lon = zip(*(h3.cell_to_latlng(c) for c in celdas))
    arbol = rng.uniform(0, 40, n)
    return pd.DataFrame({
        "h3_index": celdas, "h3_padre": [h3.cell_to_parent(c, 7) for c in celdas], "comuna": "Mock", "lat": lat, "lon": lon,
        "lst_c": rng.uniform(30, 45, n), "ndvi": rng.uniform(0.05, 0.6, n),
        "copa_modelo_pct": arbol * 0.7, "arbol_pct": arbol, "pasto_pct": rng.uniform(0, 100 - arbol), "construido_pct": rng.uniform(20, 90, n),
        "poblacion": rng.integers(100, 2000, n), "social": rng.uniform(0, 1, n),
        "es_parque": np.isin(np.arange(n), [0, 20, 27]), "vulnerabilidad": rng.uniform(0, 1, n),
    }).round(4).astype(TIPOS)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--origen", type=Path, default=Path("datos/salida_h3_gs/santiago_h3.parquet"))
    p.add_argument("--comunas", default=",".join(COMUNAS_DEMO))
    p.add_argument("--km", type=float, default=3.0)
    p.add_argument("--data", type=Path, default=Path("data"))
    a = p.parse_args()
    a.data.mkdir(exist_ok=True)
    comunas = [c.strip() for c in a.comunas.split(",")]

    demo, r = con_corredor(armar(a.origen, comunas), a.km)
    demo.to_parquet(a.data / "santiago_h3.parquet", index=False)
    gs, r_gs = con_corredor(armar(a.origen), a.km)
    gs.to_parquet(a.data / "santiago_h3_gs.parquet", index=False)
    mock(demo).to_parquet(a.data / "santiago_h3_mock.parquet", index=False)

    por = demo.groupby("comuna")

    def poca_sombra(d):  # verde para el satélite, pero casi sin árboles
        return (d["ndvi"] >= 0.3) & (d["copa_modelo_pct"] < 5) & ~d["es_parque"]

    cifras = {
        "comunas": comunas,
        "lst_c_media": por["lst_c"].mean().round(1).to_dict(),
        "copa_modelo_pct_medio": por["copa_modelo_pct"].mean().round(1).to_dict(),
        "arbol_pct_worldcover_medio": por["arbol_pct"].mean().round(1).to_dict(),
        "pasto_pct_medio": por["pasto_pct"].mean().round(1).to_dict(),
        "urgencia_media": por["urgencia"].mean().round(3).to_dict(),
        "verde_satelite_poca_sombra": {
            "criterio": "ndvi >= 0,3 y copa_modelo_pct < 5, sin parques",
            "demo": poca_sombra(demo).groupby(demo["comuna"]).sum().to_dict(),
            "gran_santiago": int(poca_sombra(gs).sum()),
            "gran_santiago_pct_de_los_ndvi_alto": round(100 * poca_sombra(gs).sum()
                                                        / ((gs["ndvi"] >= 0.3) & ~gs["es_parque"]).sum(), 1),
            "gran_santiago_top": poca_sombra(gs).groupby(gs["comuna"]).sum().nlargest(5).to_dict()},
        "corredor": {"km": round(r["length_km"], 2), "hexagonos": len(r["hexes"]), "tramos": len(r["tramos"]),
                     "por_comuna": demo.loc[demo["en_corredor"], "comuna"].value_counts().to_dict(),
                     "urgencia_cubierta": round(r["urgencia_cubierta"], 3),
                     "urgencia_azar": round(r["urgencia_azar"], 3),
                     "personas_cubiertas": r["personas_cubiertas"], "personas_azar": r["personas_azar"]},
        "corredor_gran_santiago": {"por_comuna": gs.loc[gs["en_corredor"], "comuna"].value_counts().to_dict(),
                                   "urgencia_cubierta": round(r_gs["urgencia_cubierta"], 3),
                                   "urgencia_azar": round(r_gs["urgencia_azar"], 3),
                                   "personas_cubiertas": r_gs["personas_cubiertas"],
                                   "personas_azar": r_gs["personas_azar"]},
    }
    (a.data / "cifras_pitch.json").write_text(json.dumps(cifras, ensure_ascii=False, indent=2))
    print(json.dumps(cifras, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
