"""Pruebas del Rol 2 (sensores en vivo). Uso: python -m pytest tests/test_rol2.py"""
import math
from pathlib import Path

import h3
import pandas as pd

import calidad
import fuentes
import interpolar

AHORA = pd.Timestamp("2026-11-21 15:00", tz="UTC")
LIVE_COLS = ["h3_padre", "temp_aire_c", "humedad_pct", "indice_calor_c", "anomalia_c",
             "n_sensores", "dist_min_km", "confianza", "medido_en"]


def lectura(source, lat, lon, temp, hum=40.0, minutos=0, oficial=False, bajo_techo=False):
    return {"source": source, "lat": lat, "lon": lon, "temp_c": temp, "humedad_pct": hum,
            "medido_en": AHORA - pd.Timedelta(minutes=minutos), "oficial": oficial, "bajo_techo": bajo_techo}


LAT, LON = -33.43, -70.61


def test_indice_calor_valores_conocidos():
    assert list(calidad.indice_calor([32, 32, 25], [50, 25, 40])) == [34.4, 30.3, 24.6]
    assert calidad.indice_calor(20.0, float("nan")) == 20.0  # sin humedad: la temperatura


def test_idw_un_sensor_devuelve_su_valor():
    uno = pd.DataFrame([lectura("A", LAT, LON, 20.0)])
    assert interpolar.idw(LAT, LON, uno, "temp_c")[:2] == (20.0, 1)


def test_idw_dos_equidistantes_promedia():
    dos = pd.DataFrame([lectura("A", LAT, LON + 0.01, 20.0), lectura("B", LAT, LON - 0.01, 24.0)])
    assert abs(interpolar.idw(LAT, LON, dos, "temp_c")[0] - 22.0) < 1e-6


def test_idw_sin_sensores_es_nan_y_sin_dato():
    lat, lon = LAT, LON
    lejos = pd.DataFrame([lectura("A", lat + 0.5, lon, 20.0, oficial=True)])
    v, n, d = interpolar.idw(lat, lon, lejos, "temp_c")
    assert math.isnan(v) and n == 0
    b = pd.DataFrame({"h3_padre": [h3.latlng_to_cell(lat, lon, 7)], "lat": [lat], "lon": [lon]})
    fila = interpolar.por_barrio(lejos, b).iloc[0]
    assert math.isnan(fila.temp_aire_c) and fila.confianza == "sin dato" and fila.n_sensores == 0


def test_calidad_descarta_fuera_de_rango_indoor_y_antiguos():
    df = pd.DataFrame([
        lectura("SC_ok1", -33.43, -70.61, 20.0),
        lectura("SC_ok2", -33.44, -70.62, 20.5),
        lectura("SC_ok3", -33.45, -70.63, 21.0),
        lectura("SC_frio", -33.43, -70.60, -10.0),                 # rango
        lectura("SC_viejo", -33.42, -70.61, 20.0, minutos=45),     # antigüedad
        lectura("SINCA_D18", -33.4331, -70.7321, 20.0, minutos=120, oficial=True),  # 2 h: vale para SINCA
        lectura("SC_casa", -33.41, -70.61, 22.0, bajo_techo=True),  # bajo techo
        lectura("SC_salto", -33.40, -70.62, 27.0),                 # salto vs. ciclo anterior
        lectura("SC_dup", -33.4302, -70.61, 20.2),                 # a ~22 m de SC_ok1
        lectura("SC_raro", -33.44, -70.60, 30.0),                  # vecinos
    ])
    previo = pd.DataFrame([lectura("SC_salto", -33.40, -70.62, 21.0, minutos=5)])
    buenas, n = calidad.filtrar(df, AHORA, previo)
    assert n == {"rango": 1, "antiguedad": 1, "bajo_techo": 1, "salto": 1, "duplicados": 1, "vecinos": 1}, n
    assert set(buenas.source) == {"SC_ok1", "SC_ok2", "SC_ok3", "SINCA_D18"}


def test_live_cumple_contrato():
    ruta = Path("data/live_h3.parquet")
    live = pd.read_parquet(ruta)
    assert all(c in live for c in LIVE_COLS)
    assert live.h3_padre.is_unique and all(h3.get_resolution(h) == 7 for h in live.h3_padre)
    assert set(live.confianza) <= {"alta", "media", "baja", "sin dato"}
    sin = live.confianza == "sin dato"
    assert live.loc[sin, "temp_aire_c"].isna().all() and live.loc[~sin, "temp_aire_c"].notna().all()
    assert live.loc[~sin, "medido_en"].map(pd.Timestamp).notna().all()


def test_union_con_grilla_no_pierde_cuadras():
    grilla = pd.read_parquet("data/santiago_h3.parquet")
    live = pd.read_parquet("data/live_h3.parquet")
    unida = grilla.merge(live, left_on=grilla.h3_index.map(lambda h: h3.cell_to_parent(h, 7)),
                         right_on="h3_padre", how="left", suffixes=("", "_vivo"))
    assert len(unida) == len(grilla) and unida.confianza.notna().all()


def test_ciudadano_solo_cuenta_a_menos_de_2_km():
    # a ~3,3 km: la estación oficial cuenta, el sensor ciudadano no
    s = pd.DataFrame([lectura("RM_x", LAT + 0.03, LON, 30.0), lectura("DMC_y", LAT - 0.03, LON, 20.0, oficial=True)])
    assert interpolar.idw(LAT, LON, s, "temp_c")[:2] == (20.0, 1)
    cerca = pd.DataFrame([lectura("RM_x", LAT + 0.01, LON, 30.0)])  # ~1,1 km
    assert interpolar.idw(LAT, LON, cerca, "temp_c")[:2] == (30.0, 1)


def test_redmeteo_filtra_qc_y_distancia():
    base = {"latitud": -33.45, "longitud": -70.65, "fecha_hora": "2026-11-21T15:37:44Z",
            "temperatura": 24.6, "humedad": 40.0, "QC": 0}
    estaciones = [
        {**base, "id_estacion": "RMCL0001"},
        {**base, "id_estacion": "RMCL0002", "QC": 16},             # alarma de presión: sirve
        {**base, "id_estacion": "RMCL0003", "QC": 1},              # alarma de temperatura
        {**base, "id_estacion": "RMCL0004", "QC": 64},             # estación pegada
        {**base, "id_estacion": "RMCL0005", "latitud": -18.47},   # Arica
        {**base, "id_estacion": "RMCL0006", "temperatura": None},
    ]
    t = fuentes.redmeteo_tabla(estaciones)
    assert list(t.source) == ["RM_RMCL0001", "RM_RMCL0002"]
    assert t.medido_en[0] == pd.Timestamp("2026-11-21 15:37:44", tz="UTC") and not t.oficial.any()


def test_dmc_tabla_lista_y_objeto():
    est = {"codigoNacional": "330020", "latitud": "-33.445", "longitud": "-70.683"}
    datos = [{"momento": "2026-11-21 15:01:00", "temperatura": "27.5 °C", "humedadRelativa": "21 %"},
             {"momento": "2026-11-21 15:00:00", "temperatura": None, "humedadRelativa": "22 %"}]
    red = fuentes.dmc_tabla({"datosEstaciones": [{"estacion": est, "datos": datos}]})
    una = fuentes.dmc_tabla({"datosEstaciones": {"estacion": est, "datos": datos}})
    assert len(red) == len(una) == 1 and red.temp_c[0] == 27.5 and red.humedad_pct[0] == 21.0
