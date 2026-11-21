"""Control de calidad de lecturas e índice de calor NOAA."""
import numpy as np
import pandas as pd

# Antigüedad máxima por prefijo de source. SINCA publica promedios horarios con 1 a 3 h de retraso:
# con 30 min no quedaría ninguna estación oficial, así que para esa red se acepta hasta 3 h.
MAX_EDAD_MIN = {"SC_": 30, "DMC_": 30, "SINCA_": 180}


def distancia_km(lat1, lon1, lat2, lon2):
    """Haversine; acepta arreglos (se difunden como numpy)."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def indice_calor(temp_c, humedad_pct):
    """Índice de calor NOAA/NWS (Rothfusz con ajustes), en °C. Sin humedad devuelve la temperatura."""
    tc = np.asarray(temp_c, float)
    t = tc * 9 / 5 + 32
    rh = np.asarray(humedad_pct, float)
    simple = 0.5 * (t + 61 + (t - 68) * 1.2 + rh * 0.094)
    hi = (-42.379 + 2.04901523 * t + 10.14333127 * rh - 0.22475541 * t * rh - 6.83783e-3 * t ** 2
          - 5.481717e-2 * rh ** 2 + 1.22874e-3 * t ** 2 * rh + 8.5282e-4 * t * rh ** 2
          - 1.99e-6 * t ** 2 * rh ** 2)
    with np.errstate(invalid="ignore"):
        hi = np.where((rh < 13) & (t >= 80) & (t <= 112),
                      hi - (13 - rh) / 4 * np.sqrt((17 - np.abs(t - 95)) / 17), hi)
        hi = np.where((rh > 85) & (t >= 80) & (t <= 87), hi + (rh - 85) / 10 * (87 - t) / 5, hi)
    hi = np.where((simple + t) / 2 < 80, simple, hi)
    return np.round(np.where(np.isnan(rh), tc, (hi - 32) * 5 / 9), 1)


def _duplicados(df):
    """Promedia lecturas a menos de 50 m entre sí (se queda con el source y la hora más reciente)."""
    df = df.sort_values("medido_en", ascending=False).reset_index(drop=True)
    grupo = np.full(len(df), -1)
    for i in range(len(df)):
        if grupo[i] < 0:
            cerca = distancia_km(df.lat[i], df.lon[i], df.lat.values, df.lon.values) < 0.05
            grupo[cerca & (grupo < 0)] = i
    g = df.assign(g=grupo).groupby("g")
    out = g.first()
    out[["lat", "lon", "temp_c", "humedad_pct"]] = g[["lat", "lon", "temp_c", "humedad_pct"]].mean()
    return out.reset_index(drop=True), len(df) - len(out)


def filtrar(df, ahora, previo=None):
    """Aplica los filtros en orden. Devuelve (lecturas buenas, {filtro: descartadas}).

    previo: lecturas aceptadas en el ciclo anterior (para el salto brusco).
    """
    n = {}

    def quitar(nombre, malo):
        nonlocal df
        n[nombre] = int(malo.sum())
        df = df[~malo].reset_index(drop=True)

    quitar("rango", ~df.temp_c.between(-5, 45) | (df.humedad_pct.notna() & ~df.humedad_pct.between(0, 100)))
    edad = (ahora - df.medido_en).dt.total_seconds() / 60
    limite = df.source.map(lambda s: next(v for k, v in MAX_EDAD_MIN.items() if s.startswith(k)))
    quitar("antiguedad", edad > limite)
    quitar("bajo_techo", df.bajo_techo.astype(bool))
    if previo is not None and len(previo):
        p = previo.set_index("source")[["temp_c", "medido_en"]]
        m = df.join(p, on="source", rsuffix="_ant")
        dt = (m.medido_en - m.medido_en_ant).dt.total_seconds() / 60
        quitar("salto", ((m.temp_c - m.temp_c_ant).abs() > 4) & dt.between(0.1, 10))
    else:
        n["salto"] = 0
    df, n["duplicados"] = _duplicados(df)
    malo = np.zeros(len(df), bool)
    for i in range(len(df)):
        d = distancia_km(df.lat[i], df.lon[i], df.lat.values, df.lon.values)
        vecinos = (d < 10) & (np.arange(len(df)) != i)
        if vecinos.sum() >= 2:
            malo[i] = abs(df.temp_c[i] - df.temp_c[vecinos].median()) > 5
    quitar("vecinos", pd.Series(malo))
    return df, n
