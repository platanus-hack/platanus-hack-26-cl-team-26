"""Máxima del día: regla de huecos y una fila por estación. Uso: python -m pytest tests/test_maximas.py"""
import datetime as dt

import pandas as pd

import maximas

DIA = dt.date(2026, 11, 21)


def lecturas(horas_temp, dia="2026-11-21"):
    """{hora de Santiago: temp} → lecturas de una estación."""
    t = [pd.Timestamp(f"{dia} {h:02d}:30", tz="America/Santiago").tz_convert("UTC") for h in horas_temp]
    return pd.DataFrame({"source": "DMC_1", "lat": -33.45, "lon": -70.65, "temp_c": list(horas_temp.values()),
                         "humedad_pct": 30.0, "medido_en": t, "oficial": True, "bajo_techo": False})


def test_maxima_del_dia_y_hora():
    m = maximas.maxima(lecturas({10: 18.0, 14: 26.0, 15: 28.5, 16: 27.0, 17: 25.0}), DIA)
    assert m.temp_c == 28.5 and m.medido_en.tz_convert("America/Santiago").hour == 15


def test_hueco_en_horas_de_calor_deja_fuera_la_estacion():
    assert maximas.maxima(lecturas({10: 18.0, 11: 20.0, 14: 26.0, 15: 27.0}), DIA) is None  # solo 2 de 4 horas


def test_no_mezcla_otro_dia_ni_valores_fuera_de_rango():
    hoy = lecturas({14: 26.0, 15: 50.0, 16: 27.0, 17: 25.0})
    ayer = lecturas({14: 33.0, 15: 33.0, 16: 33.0}, dia="2026-11-20")
    m = maximas.maxima(pd.concat([hoy, ayer], ignore_index=True), DIA)
    assert m.temp_c == 27.0


def test_dmc_tabla_lista_objeto_y_estacion_sin_datos():
    import fuentes
    est = {"codigoNacional": "330020", "latitud": "-33.445", "longitud": "-70.683"}
    datos = [{"momento": "2026-11-21 18:01:00", "temperatura": "27.5 °C", "humedadRelativa": "21 %"},
             {"momento": "2026-11-21 18:00:00", "temperatura": None, "humedadRelativa": "22 %"}]
    red = fuentes.dmc_tabla({"datosEstaciones": [{"estacion": est, "datos": datos},
                                                 {"estacion": {**est, "codigoNacional": "330021"}, "datos": None}]})
    una = fuentes.dmc_tabla({"datosEstaciones": {"estacion": est, "datos": datos}})
    assert len(red) == len(una) == 1 and red.temp_c[0] == 27.5 and red.humedad_pct[0] == 21.0


def test_juntar_suma_sinca_sin_perder_dmc_ni_duplicar():
    dmc = maximas.maxima(lecturas({14: 26.0, 15: 28.0, 16: 27.0}), DIA).to_frame().T
    sinca_viejo = dmc.assign(source="SINCA_D14", temp_c=20.0)
    previas = pd.concat([dmc, sinca_viejo], ignore_index=True)
    previas["medido_en"] = previas.medido_en.astype(str)  # como vuelve del CSV
    nuevas = dmc.assign(source="SINCA_D14", temp_c=24.0)
    j = maximas.juntar(previas, nuevas)
    assert sorted(j.source) == ["DMC_1", "SINCA_D14"] and j.set_index("source").temp_c.to_dict() == {"DMC_1": 28.0, "SINCA_D14": 24.0}
