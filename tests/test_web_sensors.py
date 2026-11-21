"""Control de calidad e índice de calor de web_sensors.py (Rol 2)."""
from datetime import datetime, timedelta, timezone

import pytest

from web_sensors import control_calidad, indice_calor, parsear_dmc

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


RESPUESTA_DMC = {"datosEstaciones": [
    {"estacion": {"codigoNacional": "330020", "latitud": "-33.445", "longitud": "-70.683"},
     "datos": [{"momento": "2026-11-21 15:01:00", "temperatura": "27.5 °C", "humedadRelativa": "21 %"},
               {"momento": "2026-11-21 13:00:00", "temperatura": "24.1 °C", "humedadRelativa": "30 %"},
               {"momento": "2026-11-21 14:00:00", "temperatura": None, "humedadRelativa": "25 %"}]},
    {"estacion": {"codigoNacional": "180005", "latitud": "-18.35", "longitud": "-70.34"},
     "datos": [{"momento": "2026-11-21 15:01:00", "temperatura": "20.2 °C", "humedadRelativa": "65 %"}]},
]}


def test_parsear_dmc_ultima_por_estacion_y_solo_santiago():
    [x] = parsear_dmc(RESPUESTA_DMC)
    assert (x["source"], x["temp_c"], x["humedad_pct"]) == ("DMC_330020", 27.5, 21.0)
    assert x["timestamp"] == "2026-11-21T15:01:00+00:00"


def test_parsear_dmc_todas_en_orden_y_sin_temperatura_vacia():
    xs = parsear_dmc(RESPUESTA_DMC, todas=True)
    assert [x["temp_c"] for x in xs] == [24.1, 27.5]


def test_calidad_humedad_invalida_pasa_a_none():
    [x] = control_calidad([lect(hum=140.0)], [], AHORA)
    assert x["humedad_pct"] is None
