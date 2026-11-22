"""Temperatura máxima del día por barrio. Corre una vez al día, pasada la medianoche de Santiago
(.github/workflows/maximas.yml), y escribe data/live_h3.parquet con las columnas de siempre:
temp_aire_c es la máxima de ayer y medido_en la hora en que se midió.

Uso:
  python maximas.py               # ayer, en hora de Santiago
  python maximas.py 2026-11-21    # otro día (la DMC solo guarda 12 h: sirve hasta el mediodía siguiente)

Fuentes: solo estaciones oficiales. DMC (getDatosRecientesEma/{codigo}, minuto a minuto, 12 h) y SINCA
(promedio horario). sensor.community no guarda el día y RedMeteo no tiene acceso confirmado.
Huecos: una estación entra solo si tiene datos en al menos 3 de las 4 horas más calientes (14 a 18 h);
con menos, su máxima podría quedar baja, así que se deja fuera y el barrio usa las vecinas o queda «sin dato».
Duplicados: una fila por estación; estaciones a menos de 50 m se promedian (calidad); volver a correr el
mismo día reescribe los archivos, no agrega filas.
También guarda data/maximas/AAAA-MM-DD.csv (la máxima de cada estación), como historial.
"""
import io
import sys
from pathlib import Path

import pandas as pd
import requests

import calidad
import fuentes
import interpolar
import vivo

HORAS_CALOR = range(14, 18)   # 14:00 a 17:59 de Santiago
MIN_HORAS = 3
HISTORIAL = vivo.DATA / "maximas"


def maxima(lecturas, dia):
    """Lecturas de una estación (columnas de fuentes.COLUMNAS) → su fila con la máxima del día, o None."""
    local = lecturas.medido_en.dt.tz_convert(fuentes.TZ)
    del_dia = lecturas[(local.dt.date == dia) & lecturas.temp_c.between(-5, 45)]
    horas = set(del_dia.medido_en.dt.tz_convert(fuentes.TZ).dt.hour)
    if len(horas & set(HORAS_CALOR)) < MIN_HORAS:
        return None
    return del_dia.loc[del_dia.temp_c.idxmax()]


def dmc_dia(dia):
    """Máxima del día de cada estación DMC de Santiago (sin token: tabla vacía)."""
    try:
        codigos = sorted(fuentes.dmc_estaciones().source.unique())
    except Exception as e:  # sin token o la DMC caída: sigue con SINCA
        print(f"DMC: {e!r}")
        return []
    filas = []
    for s in codigos:
        try:
            m = maxima(fuentes.dmc_12h(s.removeprefix("DMC_")), dia)
        except Exception as e:  # una estación caída no tumba a las demás
            print(f"{s}: {e!r}")
            continue
        if m is not None:
            filas.append(m)
    return filas


def _sinca_serie(key, var, dia):
    url = fuentes.SINCA_URL.format(key=key, var=var, desde=f"{dia:%y%m%d}", hasta=f"{dia:%y%m%d}")
    df = pd.read_csv(io.StringIO(requests.get(url, timeout=30).text), sep=";", decimal=",", header=0,
                     names=["fecha", "hora", "valor", "_"], dtype={"fecha": str, "hora": str}).dropna(subset=["valor"])
    return pd.Series(df.valor.values, index=[fuentes.hora_sinca(f, h).tz_convert("UTC") for f, h in zip(df.fecha, df.hora)])


def sinca_dia(dia):
    """Máxima del día de cada estación SINCA (promedios horarios)."""
    filas = []
    for key, (nombre, lat, lon) in fuentes.SINCA_ESTACIONES.items():
        try:
            temp, hum = _sinca_serie(key, "TEMP", dia), _sinca_serie(key, "RHUM", dia)
        except Exception as e:
            print(f"SINCA {key}: {e!r}")
            continue
        lect = pd.DataFrame({"source": f"SINCA_{key}", "lat": lat, "lon": lon, "temp_c": temp.values,
                             "humedad_pct": hum.reindex(temp.index).values, "medido_en": temp.index,
                             "oficial": True, "bajo_techo": False})
        m = maxima(lect, dia) if len(lect) else None
        if m is not None:
            filas.append(m)
    return filas


def main(args):
    dia = (pd.Timestamp(args[0]) if args else pd.Timestamp.now(tz=fuentes.TZ) - pd.Timedelta(days=1)).date()
    filas = dmc_dia(dia) + sinca_dia(dia)
    if not filas:
        print(f"{dia}: ninguna estación con datos de las horas de calor; no se escribe nada")
        return 1
    est, n_dup = calidad._duplicados(pd.DataFrame(filas)[fuentes.COLUMNAS].reset_index(drop=True))
    live = interpolar.por_barrio(est, interpolar.barrios(pd.read_parquet(vivo.grilla())))
    live["alerta"] = vivo.alerta(live, ())
    vivo.escribir(vivo.DATA / "live_h3.parquet", lambda p: live.to_parquet(p, index=False))
    HISTORIAL.mkdir(parents=True, exist_ok=True)
    est.sort_values("source").to_csv(HISTORIAL / f"{dia}.csv", index=False)
    print(f"{dia}: {len(est)} estaciones ({n_dup} duplicadas), máxima {est.temp_c.max():.1f} °C; "
          f"barrios {live.confianza.value_counts().to_dict()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
