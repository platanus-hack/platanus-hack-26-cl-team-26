"""Verifica que los archivos compartidos cumplan CONTRATO.md.

Si una IA renombra una columna o cambia un tipo, este test falla.
Los archivos que todavía no existen se saltan. Correr con: python -m pytest tests/test_contrato.py
"""
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest
from pandas.api import types as pt

RAIZ = Path(__file__).resolve().parent.parent
DATA = RAIZ / "data"

SANTIAGO = {
    "h3_index": pt.is_string_dtype,
    "comuna": pt.is_string_dtype,
    "lat": pt.is_float_dtype,
    "lon": pt.is_float_dtype,
    "lst_c": pt.is_float_dtype,
    "ndvi": pt.is_float_dtype,
    "arbol_pct": pt.is_numeric_dtype,
    "pasto_pct": pt.is_numeric_dtype,
    "construido_pct": pt.is_numeric_dtype,
    "poblacion": pt.is_integer_dtype,
    "social": pt.is_numeric_dtype,
    "es_parque": pt.is_bool_dtype,
}

LIVE = {
    "h3_index": pt.is_string_dtype,
    "temp_aire_c": pt.is_float_dtype,
    "humedad_pct": pt.is_numeric_dtype,
    "indice_calor_c": pt.is_float_dtype,
    "uv": pt.is_numeric_dtype,
    "anomalia_c": pt.is_float_dtype,
    "n_sensores": pt.is_integer_dtype,
    "alerta": pt.is_bool_dtype,
    "timestamp": pt.is_string_dtype,
}

WEB_SENSORS = {"source", "lat", "lon", "h3_index", "temp_c", "humedad_pct", "timestamp"}


def _cargar(nombre):
    ruta = DATA / nombre
    if not ruta.exists():
        pytest.skip(f"{nombre} todavía no existe")
    return pd.read_parquet(ruta)


def _revisar_columnas(df, esquema):
    faltan = [c for c in esquema if c not in df.columns]
    assert not faltan, f"faltan columnas del contrato: {faltan}"
    malos = [c for c, es_tipo in esquema.items() if not es_tipo(df[c])]
    assert not malos, f"tipos distintos al contrato: {[(c, str(df[c].dtype)) for c in malos]}"


def _revisar_h3(serie):
    import h3

    assert serie.notna().all(), "h3_index con nulos"
    malos = [h for h in serie if not h3.is_valid_cell(h) or h3.get_resolution(h) != 9]
    assert not malos, f"h3_index inválidos o no son resolución 9: {malos[:5]}"


@pytest.mark.parametrize("nombre", ["santiago_h3.parquet", "santiago_h3_mock.parquet"])
def test_santiago_h3(nombre):
    df = _cargar(nombre)
    _revisar_columnas(df, SANTIAGO)
    _revisar_h3(df["h3_index"])
    assert df["ndvi"].between(-1, 1).all()
    for c in ["arbol_pct", "pasto_pct", "construido_pct"]:
        assert df[c].between(0, 100).all(), c
    assert df["social"].between(0, 1).all()


@pytest.mark.parametrize("nombre", ["live_h3.parquet", "live_h3_mock.parquet"])
def test_live_h3(nombre):
    df = _cargar(nombre)
    _revisar_columnas(df, LIVE)
    _revisar_h3(df["h3_index"])
    assert df["humedad_pct"].between(0, 100).all()
    assert (df["n_sensores"] >= 0).all()
    for t in df["timestamp"]:
        datetime.fromisoformat(t)


def test_web_sensors():
    ruta = DATA / "web_sensors.json"
    if not ruta.exists():
        pytest.skip("web_sensors.json todavía no existe")
    lecturas = json.loads(ruta.read_text(encoding="utf-8"))
    assert isinstance(lecturas, list)
    for r in lecturas:
        assert set(r) >= WEB_SENSORS, f"faltan claves: {WEB_SENSORS - set(r)}"
        assert r["source"].startswith(("DMC_", "SC_")), r["source"]
        datetime.fromisoformat(r["timestamp"])
