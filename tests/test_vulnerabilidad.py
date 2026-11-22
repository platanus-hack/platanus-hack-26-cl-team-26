"""Vulnerabilidad al calor (Censo 2024): el índice, su peso en la urgencia y que sea solo de las personas.

Uso: python -m tests.test_vulnerabilidad
"""
from pathlib import Path

import numpy as np
import pandas as pd

from ecologia import criterio_por_especies, resolver_corredor_por_especies
from optimizer import _norm, solve_corridor, urgencia
from verdeh3.contrato import MIN_PERSONAS_VULN, vulnerabilidad

GS = Path("data/santiago_h3_gs.parquet")
SUB = ["Santiago", "Providencia", "Ñuñoa"]


def censo_sintetico(n: int = 40, semilla: int = 0) -> pd.DataFrame:
    """Conteos censo_* como los que escribe verdeh3.censo, con valores al azar pero coherentes."""
    rng = np.random.default_rng(semilla)
    per = rng.integers(100, 2000, n).astype(float)
    viv = (per / 3).round()
    return pd.DataFrame({
        "poblacion_censo": per,
        "censo_60_mas": (per * rng.uniform(0.05, 0.35, n)).round(),
        "censo_0_5": (per * rng.uniform(0.02, 0.10, n)).round(),
        "censo_discapacidad": (per * rng.uniform(0.02, 0.15, n)).round(),
        "censo_viv_ocupadas": viv,
        "censo_viv_hacinadas": (viv * rng.uniform(0, 0.2, n)).round(),
        "censo_viv_irrecuperables": (viv * rng.uniform(0, 0.05, n)).round(),
        "censo_per_escolaridad": per * 0.75,
        "censo_escolaridad_x_per": per * 0.75 * rng.uniform(8, 17, n),
    })


def test_indice():
    t = censo_sintetico()
    v = vulnerabilidad(t)["vulnerabilidad"]
    assert v.between(0, 1).all() and v.notna().all()
    # Más personas mayores en una cuadra: más vulnerable (y no cambia el resto de su fila).
    i = int(v.idxmin())
    mas_viejos = t.copy()
    mas_viejos.loc[i, "censo_60_mas"] = mas_viejos.loc[i, "poblacion_censo"] * 0.3
    assert vulnerabilidad(mas_viejos)["vulnerabilidad"].iloc[i] > v.iloc[i]
    # Más escolaridad: menos vulnerable.
    j = int(v.idxmax())
    mas_escuela = t.copy()
    mas_escuela.loc[j, "censo_escolaridad_x_per"] = mas_escuela.loc[j, "censo_per_escolaridad"] * 17
    assert vulnerabilidad(mas_escuela)["vulnerabilidad"].iloc[j] < v.iloc[j]
    # Cuadra casi vacía: sin índice propio (contrato.armar le pone la mediana de la comuna).
    vacia = t.copy()
    vacia.loc[0, "poblacion_censo"] = MIN_PERSONAS_VULN - 1
    assert np.isnan(vulnerabilidad(vacia)["vulnerabilidad"].iloc[0])
    # Sin las columnas del Censo: 0 en todas partes, con aviso, sin romper.
    assert (vulnerabilidad(t[["poblacion_censo"]])["vulnerabilidad"] == 0).all()


def test_peso_en_la_urgencia():
    df = pd.read_parquet(GS)
    sub = df[df["comuna"].isin(SUB)]
    # w_vuln = 0 deja la fórmula de antes; sin la columna, el peso no entra ni en la suma.
    viejo = urgencia(sub, 0.4, 0.4, 0.2, w_vuln=0)
    pd.testing.assert_series_equal(viejo, urgencia(sub.drop(columns="vulnerabilidad"), 0.4, 0.4, 0.2, w_vuln=0.7))
    # La vulnerabilidad suma su término normalizado, y los pesos se reescalan.
    u = urgencia(sub, 0.4, 0.4, 0.2, w_vuln=0.1)
    pd.testing.assert_series_equal(u, ((viejo * 1.0 + 0.1 * _norm(sub["vulnerabilidad"])) / 1.1).rename("urgencia"))
    assert (u != viejo).any()
    # Solo con vulnerabilidad, la urgencia es la vulnerabilidad normalizada.
    pd.testing.assert_series_equal(urgencia(sub, 0, 0, 0, w_vuln=1), _norm(sub["vulnerabilidad"]).rename("urgencia"))
    # Por omisión el corredor de todo Santiago cubre más gente que al azar, y gente más vulnerable que el promedio.
    r = solve_corridor(df, 3.0)
    assert r["personas_cubiertas"] > r["personas_azar"]
    dentro = df[df["h3_index"].isin(r["hexes"])]
    hab = df[df["poblacion"] >= 50]
    media = lambda d: (d["vulnerabilidad"] * d["poblacion"]).sum() / d["poblacion"].sum()  # noqa: E731
    assert media(dentro) > media(hab)


def test_solo_humanos():
    """Aves y abejas no miran la vulnerabilidad: su corredor no cambia con w_vuln. El de personas sí."""
    sub = pd.read_parquet(GS).query("comuna in @SUB")
    for especies in (["aves"], ["abejas"], ["aves", "abejas"]):
        a = criterio_por_especies(sub, especies, w_vuln=0)
        b = criterio_por_especies(sub, especies, w_vuln=1)
        pd.testing.assert_series_equal(a[0], b[0])
        pd.testing.assert_series_equal(a[1], b[1])
        r0 = resolver_corredor_por_especies(sub, especies, w_vuln=0)
        r1 = resolver_corredor_por_especies(sub, especies, w_vuln=1)
        assert r0["hexes_corredor"] == r1["hexes_corredor"] and r0["hexes_checkpoints"] == r1["hexes_checkpoints"], especies
    h0 = criterio_por_especies(sub, ["humanos"], w_vuln=0)[0]
    h1 = criterio_por_especies(sub, ["humanos"], w_vuln=1)[0]
    assert (h0 != h1).any()
    # Con humanos y aves, la vulnerabilidad mueve la mitad humana de la prioridad.
    m0 = criterio_por_especies(sub, ["humanos", "aves"], w_vuln=0)[0]
    m1 = criterio_por_especies(sub, ["humanos", "aves"], w_vuln=1)[0]
    assert np.allclose(m1 - m0, (h1 - h0) / 2)


def test_datos():
    """La columna de los parquet tiene el sentido esperado: Providencia menos vulnerable que Cerro Navia."""
    df = pd.read_parquet(GS)
    assert df["vulnerabilidad"].notna().all() and df["vulnerabilidad"].between(0, 1).all()
    por_comuna = df.groupby("comuna")["vulnerabilidad"].median()
    assert por_comuna["Providencia"] < por_comuna.median() < por_comuna["Cerro Navia"]


def main():
    for f in (test_indice, test_peso_en_la_urgencia, test_solo_humanos, test_datos):
        f()
        print("OK", f.__name__)


if __name__ == "__main__":
    main()
