"""Valor por barrio (hexágono H3 de resolución 7) con IDW 1/d² y su confianza."""
import h3
import numpy as np
import pandas as pd

from calidad import distancia_km, indice_calor

RES_BARRIO = 7
RADIO_KM, RADIO_AMPLIO_KM = 5.0, 8.0


def barrios(grilla):
    """Barrios únicos de la grilla de cuadras (resolución 9) con su centro."""
    padres = sorted({h3.cell_to_parent(h, RES_BARRIO) for h in grilla.h3_index})
    centros = [h3.cell_to_latlng(p) for p in padres]
    return pd.DataFrame({"h3_padre": padres, "lat": [c[0] for c in centros], "lon": [c[1] for c in centros]})


def idw(lat, lon, sensores, col, radio_km=RADIO_KM):
    """Devuelve (valor, n_sensores, dist_min_km). Sin sensores en el radio: (NaN, 0, NaN)."""
    s = sensores.dropna(subset=[col])
    d = distancia_km(lat, lon, s.lat.values, s.lon.values)
    m = d < radio_km
    if not m.any():
        return np.nan, 0, np.nan
    if (d[m] < 0.05).any():  # sensor prácticamente en el centro
        return float(s[col].values[m][d[m].argmin()]), int(m.sum()), float(d[m].min())
    w = 1 / d[m] ** 2
    return float((w * s[col].values[m]).sum() / w.sum()), int(m.sum()), float(d[m].min())


def confianza(n, dist_min, amplio=False):
    if n == 0:
        return "sin dato"
    if amplio:
        return "baja"
    if n >= 3 and dist_min < 2:
        return "alta"
    return "media" if n >= 2 else "baja"


def con_anomalia(sensores, ventana=pd.Timedelta("30min")):
    """Anomalía de cada sensor ciudadano: su temperatura menos la estación oficial más cercana medida
    a menos de 30 min de él (no se compara contra un promedio horario de hace 2 h).
    Sin estaciones oficiales a tiempo (plan B), contra la mediana de la ciudad."""
    of = sensores[sensores.oficial]
    an = []
    for r in sensores.itertuples():
        if r.oficial:
            an.append(np.nan)
            continue
        ok = of[(of.medido_en - r.medido_en).abs() <= ventana]
        ref = (ok.temp_c.values[distancia_km(r.lat, r.lon, ok.lat.values, ok.lon.values).argmin()]
               if len(ok) else sensores.temp_c.median())
        an.append(r.temp_c - ref)
    return sensores.assign(anomalia_c=an)


def por_barrio(sensores, b):
    """Una fila por barrio con las columnas de data/live_h3.parquet."""
    s = con_anomalia(sensores)
    filas = []
    for r in b.itertuples():
        t, n, dmin = idw(r.lat, r.lon, s, "temp_c")
        amplio = n == 0
        radio = RADIO_AMPLIO_KM if amplio else RADIO_KM
        if amplio:
            t, n, dmin = idw(r.lat, r.lon, s, "temp_c", radio)
        hum = idw(r.lat, r.lon, s, "humedad_pct", radio)[0]
        an = idw(r.lat, r.lon, s, "anomalia_c", radio)[0]
        usados = s[distancia_km(r.lat, r.lon, s.lat.values, s.lon.values) < radio]
        filas.append({
            "h3_padre": r.h3_padre,
            "temp_aire_c": round(t, 2) if n else np.nan,
            "humedad_pct": round(hum, 1) if n else np.nan,
            "indice_calor_c": float(indice_calor(t, hum)) if n else np.nan,
            "anomalia_c": round(an, 2) if n else np.nan,
            "n_sensores": n,
            "dist_min_km": round(dmin, 2) if n else np.nan,
            "confianza": confianza(n, dmin, amplio),
            "medido_en": usados.medido_en.max().isoformat() if n else None,
        })
    return pd.DataFrame(filas)
