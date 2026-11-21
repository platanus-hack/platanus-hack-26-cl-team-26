"""Control de calidad e índice de calor de web_sensors.py (Rol 2)."""
from datetime import datetime, timedelta, timezone

import pytest

from web_sensors import control_calidad, indice_calor

AHORA = datetime(2026, 11, 21, 18, 0, tzinfo=timezone.utc)


def lect(source="SC_1", temp=25.0, hum=40.0, minutos_atras=5):
    t = (AHORA - timedelta(minutes=minutos_atras)).isoformat()
    return {"source": source, "lat": -33.45, "lon": -70.65, "h3_index": "89b2c556ba3ffff",
            "temp_c": temp, "humedad_pct": hum, "timestamp": t}


# Tabla de índice de calor de la NOAA (°F): 90/40 -> 91, 100/40 -> 109, 96/65 -> 121
@pytest.mark.parametrize("temp_f, hum, esperado_f", [(90, 40, 91), (100, 40, 109), (96, 65, 121)])
def test_indice_calor_tabla_noaa(temp_f, hum, esperado_f):
    temp_c = (temp_f - 32) * 5 / 9
    assert indice_calor(temp_c, hum) == pytest.approx((esperado_f - 32) * 5 / 9, abs=0.7)


def test_indice_calor_bajo_27_devuelve_temperatura():
    assert indice_calor(22.0, 50) == 22.0


def test_indice_calor_sin_humedad_devuelve_temperatura():
    assert indice_calor(33.0, None) == 33.0


def test_indice_calor_aire_seco_de_santiago_no_supera_la_temperatura_por_mucho():
    assert indice_calor(33.0, 15) <= 33.0 + 0.5


def test_calidad_deja_lectura_normal():
    assert len(control_calidad([lect()], [], AHORA)) == 1


@pytest.mark.parametrize("temp", [-30.0, 60.0])
def test_calidad_descarta_temperatura_imposible(temp):
    assert control_calidad([lect(temp=temp)], [], AHORA) == []


def test_calidad_descarta_lectura_antigua():
    assert control_calidad([lect(minutos_atras=90)], [], AHORA) == []


def test_calidad_descarta_salto_brusco():
    previa = lect(temp=25.0, minutos_atras=15)
    assert control_calidad([lect(temp=31.0, minutos_atras=5)], [previa], AHORA) == []


def test_calidad_acepta_cambio_gradual():
    previa = lect(temp=25.0, minutos_atras=15)
    assert len(control_calidad([lect(temp=26.5, minutos_atras=5)], [previa], AHORA)) == 1


def test_calidad_humedad_invalida_pasa_a_none():
    [x] = control_calidad([lect(hum=140.0)], [], AHORA)
    assert x["humedad_pct"] is None
