"""Temperatura máxima del día por barrio. Corre una vez al día, pasada la medianoche de Santiago
(.github/workflows/maximas.yml), y escribe data/live_h3.parquet con las columnas de siempre:
temp_aire_c es la máxima de ayer y medido_en la hora en que se midió.

Uso:
  python maximas.py               # ayer, en hora de Santiago
  python maximas.py 2026-11-21    # otro día (la DMC solo guarda 12 h: sirve hasta el mediodía siguiente)
  python maximas.py --completar   # suma SINCA a los días de las últimas 2 semanas que no lo tienen
                                  # (desde Chile; lo corre scripts/completar_sinca.sh con un timer de systemd)

Fuentes: solo estaciones oficiales. DMC (getDatosRecientesEma/{codigo}, minuto a minuto, 12 h) y SINCA
(promedio horario). sensor.community no guarda el día y RedMeteo no tiene acceso confirmado.
Huecos: una estación entra solo si tiene datos en al menos 3 de las 4 horas más calientes (14 a 18 h);
con menos, su máxima podría quedar baja, así que se deja fuera y el barrio usa las vecinas o queda «sin dato».
Duplicados: una fila por estación; estaciones a menos de 50 m se promedian (calidad). Volver a correr un día
junta lo nuevo con data/maximas/AAAA-MM-DD.csv: cada estación queda una vez (la lectura nueva reemplaza a la
anterior) y las que ya no se pueden pedir se conservan.
SINCA bloquea las conexiones desde fuera de Chile (403 desde GitHub Actions, que corre en EE. UU.). La tarea
diaria trae la DMC; SINCA guarda su historial, así que se suma después desde un PC en Chile con
`python maximas.py AAAA-MM-DD` sin perder la DMC del día. live_h3.parquet solo se reescribe con el día más
reciente del historial.
"""
import datetime as dt
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
DIAS_COMPLETAR = 14
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
    r = requests.get(url, timeout=30)
    r.raise_for_status()  # desde fuera de Chile: 403
    df = pd.read_csv(io.StringIO(r.text), sep=";", decimal=",", header=0,
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


def pendientes(hoy, n=DIAS_COMPLETAR):
    """Días de los últimos n, desde el primero del historial, sin ninguna estación SINCA, del más antiguo al
    más reciente. Ayer entra solo si la tarea de la noche ya dejó su archivo, para no escribir los dos a la vez."""
    archivos = sorted(HISTORIAL.glob("*.csv"))
    if not archivos:
        return []
    primero = dt.date.fromisoformat(archivos[0].stem)
    dias = []
    for k in range(n, 0, -1):
        d = hoy - dt.timedelta(days=k)
        if d < primero:
            continue
        ruta = HISTORIAL / f"{d}.csv"
        if ruta.exists():
            if not pd.read_csv(ruta).source.str.startswith("SINCA_").any():
                dias.append(d)
        elif k >= 2:
            dias.append(d)
    return dias


def main(args):
    hoy = pd.Timestamp.now(tz=fuentes.TZ).date()
    if args[:1] == ["--completar"]:
        dias = pendientes(hoy, int(args[1]) if len(args) > 1 else DIAS_COMPLETAR)
        print(f"Días sin SINCA: {', '.join(map(str, dias)) or 'ninguno'}")
        for d in dias:
            guardar(d, sinca_dia(d))
        return 0
    dia = pd.Timestamp(args[0]).date() if args else hoy - dt.timedelta(days=1)
    return guardar(dia, dmc_dia(dia) + sinca_dia(dia))


def guardar(dia, filas):
    """Junta las máximas nuevas con el historial del día y, si es el día más reciente, reescribe live_h3."""
    if not filas:
        print(f"{dia}: ninguna estación con datos de las horas de calor; no se escribe nada")
        return 1
    ruta = HISTORIAL / f"{dia}.csv"
    nuevas = pd.DataFrame(filas)[fuentes.COLUMNAS]
    est = juntar(pd.read_csv(ruta, parse_dates=["medido_en"]) if ruta.exists() else None, nuevas)
    HISTORIAL.mkdir(parents=True, exist_ok=True)
    est.sort_values("source").to_csv(ruta, index=False)
    est, n_dup = calidad._duplicados(est)
    print(f"{dia}: {len(est)} estaciones ({len(nuevas)} nuevas, {n_dup} duplicadas), máxima {est.temp_c.max():.1f} °C")
    if max(HISTORIAL.glob("*.csv")).stem != str(dia):
        print("Hay un día más reciente en el historial: live_h3.parquet no se toca")
        return 0
    live = interpolar.por_barrio(est, interpolar.barrios(pd.read_parquet(vivo.grilla())))
    live["alerta"] = vivo.alerta(live, ())
    vivo.escribir(vivo.DATA / "live_h3.parquet", lambda p: live.to_parquet(p, index=False))
    print(f"barrios {live.confianza.value_counts().to_dict()}")
    return 0


def juntar(previas, nuevas):
    """Una fila por estación: la nueva reemplaza a la anterior; las anteriores que no volvieron se quedan."""
    if previas is None or not len(previas):
        return nuevas.reset_index(drop=True)
    previas = previas[fuentes.COLUMNAS].assign(medido_en=pd.to_datetime(previas.medido_en, utc=True))
    quedan = previas[~previas.source.isin(nuevas.source)]
    return pd.concat([quedan, nuevas], ignore_index=True).astype({"oficial": bool, "bajo_techo": bool})


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
