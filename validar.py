"""Validación dejando un sensor fuera → data/validacion.json.

Para cada instante y cada sensor, se estima su temperatura con los demás (IDW igual que por barrio:
5 km, y 8 km si no hay nada) y se compara con usar el promedio de la ciudad (los demás sensores).

Uso:
  python validar.py              # usa data/grabacion/
  HISTORIA_H=48 python validar.py   # además baja las últimas 48 h horarias de SINCA
Siempre suma la última hora de la Dirección Meteorológica (un instante cada 10 min).
"""
import io
import json
import os

import numpy as np
import pandas as pd
import requests

import fuentes
import interpolar


def historia_sinca(horas):
    """Lecturas horarias de las estaciones SINCA de las últimas `horas`, con ahora = su hora."""
    hoy = pd.Timestamp.now(tz=fuentes.TZ)
    desde = (hoy - pd.Timedelta(hours=horas)).strftime("%y%m%d")
    filas = []
    for key, (_, lat, lon) in fuentes.SINCA_ESTACIONES.items():
        url = fuentes.SINCA_URL.format(key=key, var="TEMP", desde=desde, hasta=hoy.strftime("%y%m%d"))
        df = pd.read_csv(io.StringIO(requests.get(url, timeout=30).text), sep=";", decimal=",", header=0,
                         names=["fecha", "hora", "temp_c", "_"], dtype={"fecha": str, "hora": str}).dropna(subset=["temp_c"])
        for r in df.itertuples():
            filas.append({"source": f"SINCA_{key}", "lat": lat, "lon": lon, "temp_c": r.temp_c, "oficial": True,
                          "instante": str(fuentes.hora_sinca(r.fecha, r.hora).tz_convert("UTC")), "origen": "SINCA"})
    return pd.DataFrame(filas)


def instantes_grabados():
    import vivo
    if not list(vivo.GRAB.glob("*.csv")):
        return pd.DataFrame()
    g = vivo.leer_grabacion()
    # el conjunto que vio el ciclo en vivo, un instante cada 30 min (no repetir la misma lectura horaria)
    g["instante"] = g.leido_en.dt.floor("30min").astype(str)
    g = g.drop_duplicates(["source", "instante"])[["source", "lat", "lon", "temp_c", "oficial", "instante"]]
    return g.assign(origen="grabacion")


def reciente_dmc():
    """La última hora de la Dirección Meteorológica, un instante cada 10 min."""
    h = fuentes.dmc_estaciones()
    h = h[h.medido_en.dt.minute % 10 == 0]
    return h.assign(instante=h.medido_en.astype(str), origen="DMC")[
        ["source", "lat", "lon", "temp_c", "oficial", "instante", "origen"]]


def dejar_uno_fuera(lecturas):
    errores, base, sin_pred, n = [], [], 0, 0
    for _, s in lecturas.groupby("instante"):
        s = s.reset_index(drop=True)
        if len(s) < 3:
            continue
        for i in range(len(s)):
            resto = s.drop(index=i)
            n += 1
            pred = interpolar.idw(s.lat[i], s.lon[i], resto, "temp_c")[0]
            if np.isnan(pred):
                pred = interpolar.idw(s.lat[i], s.lon[i], resto, "temp_c", interpolar.RADIO_AMPLIO_KM)[0]
            if np.isnan(pred):
                sin_pred += 1
                continue
            errores.append(abs(pred - s.temp_c[i]))
            base.append(abs(resto.temp_c.mean() - s.temp_c[i]))
    return errores, base, sin_pred, n


def resumen(lecturas):
    errores, base, sin_pred, n = dejar_uno_fuera(lecturas)
    mae, mae_base = (float(np.mean(errores)), float(np.mean(base))) if errores else (None, None)
    return {
        "casos": n, "con_estimacion": len(errores), "sin_vecino_a_8km": sin_pred,
        "instantes": int(lecturas.instante.nunique()), "sensores": int(lecturas.source.nunique()),
        "error_medio_idw_c": round(mae, 2) if mae is not None else None,
        "error_medio_promedio_ciudad_c": round(mae_base, 2) if mae_base is not None else None,
        "idw_mejor_que_promedio": bool(mae < mae_base) if mae is not None else None,
    }


def main():
    partes = [instantes_grabados(), reciente_dmc()]
    if os.getenv("HISTORIA_H"):
        partes.append(historia_sinca(int(os.getenv("HISTORIA_H"))))
    lecturas = pd.concat([p for p in partes if len(p)], ignore_index=True).drop_duplicates(["origen", "source", "instante"])
    # el instante solo agrupa dentro de un mismo origen
    lecturas["instante"] = lecturas.origen + " " + lecturas.instante
    hora = pd.to_datetime(lecturas.instante.str.split(" ", n=1).str[1], utc=True, format="ISO8601").dt.tz_convert(fuentes.TZ).dt.hour
    res = {"calculado_en": pd.Timestamp.now(tz=fuentes.TZ).isoformat(), "todo": resumen(lecturas),
           "manana_6_12h": resumen(lecturas[hora.between(6, 11)]),
           "tarde_12_20h": resumen(lecturas[hora.between(12, 19)]),
           "por_origen": {o: resumen(g) for o, g in lecturas.groupby("origen")}}
    tmp = "data/validacion.json.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    os.replace(tmp, "data/validacion.json")
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
