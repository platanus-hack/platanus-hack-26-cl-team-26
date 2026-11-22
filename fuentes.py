"""Lectores de sensores en vivo. Cada uno devuelve la misma tabla (COLUMNAS).

Formatos vistos en data/muestras/ (21-11-2026):
- sensor.community: lista de lecturas; location.latitude/longitude/indoor (texto), timestamp en UTC
  "AAAA-MM-DD hh:mm:ss", sensordatavalues = [{value_type, value}] con "temperature" y "humidity".
- SINCA (Ministerio del Medio Ambiente): CSV "AAMMDD;hhmm;valor;" con coma decimal, promedio horario
  en hora local de Santiago; las horas aún sin dato vienen vacías.
- Dirección Meteorológica: getDatosRecientesRedEma exige usuario y token (DMC_USUARIO, DMC_TOKEN en .env).
  datosEstaciones = [{estacion: {codigoNacional, latitud, longitud (texto)}, datos: [{momento en UTC
  "AAAA-MM-DD hh:mm:ss", temperatura "19.3 °C", humedadRelativa "61 %"}]}], cada 10 min, la más nueva primero.
"""
import io
import os

import pandas as pd
import requests

COLUMNAS = ["source", "lat", "lon", "temp_c", "humedad_pct", "medido_en", "oficial", "bajo_techo"]
TZ = "America/Santiago"

SC_URL = "https://data.sensor.community/airrohr/v1/filter/area=-33.45,-70.65,25"
SINCA_URL = ("https://sinca.mma.gob.cl/cgi-bin/APUB-MMA/apub.tsindico2.cgi?outtype=xcl"
             "&macro=./RM/{key}/Met/{var}/horario_003.ic&from={desde}&to={hasta}"
             "&path=/usr/airviro/data/CONAMA/&lang=esp&rsrc=&macropath=")
# Estaciones de Santiago con TEMP y RHUM vigentes (fichas en sinca.mma.gob.cl/index.php/estacion/index/key/Dxx)
SINCA_ESTACIONES = {
    "D12": ("La Florida", -33.5166, -70.5881),
    "D13": ("Las Condes", -33.3768, -70.5233),
    "D14": ("Parque O'Higgins", -33.4641, -70.6608),
    "D15": ("Pudahuel", -33.4378, -70.7502),
    "D17": ("El Bosque", -33.5499, -70.6765),
    "D18": ("Cerro Navia", -33.4331, -70.7321),
    "D27": ("Puente Alto", -33.5914, -70.5948),
    "D28": ("Talagante", -33.6738, -70.9531),
    "D30": ("Quilicura", -33.3496, -70.7238),
}
DMC_URL = "https://climatologia.meteochile.gob.cl/application/servicios/getDatosRecientesRedEma"
DMC_EMA_URL = "https://climatologia.meteochile.gob.cl/application/servicios/getDatosRecientesEma"


def _tabla(filas):
    return pd.DataFrame(filas, columns=COLUMNAS).astype({"oficial": bool, "bajo_techo": bool})


def sensor_community(timeout=30):
    filas = []
    for r in requests.get(SC_URL, timeout=timeout).json():
        v = {x["value_type"]: x["value"] for x in r["sensordatavalues"]}
        if "temperature" not in v:
            continue
        loc = r["location"]
        filas.append({
            "source": f"SC_{r['sensor']['id']}",
            "lat": float(loc["latitude"]), "lon": float(loc["longitude"]),
            "temp_c": float(v["temperature"]),
            "humedad_pct": float(v["humidity"]) if "humidity" in v else float("nan"),
            "medido_en": pd.Timestamp(r["timestamp"], tz="UTC"),
            "oficial": False, "bajo_techo": str(loc.get("indoor")) == "1",
        })
    return _tabla(filas)


def _sinca_ultima(key, var, timeout):
    hoy = pd.Timestamp.now(tz=TZ)
    url = SINCA_URL.format(key=key, var=var, desde=(hoy - pd.Timedelta(days=1)).strftime("%y%m%d"),
                           hasta=hoy.strftime("%y%m%d"))
    df = pd.read_csv(io.StringIO(requests.get(url, timeout=timeout).text), sep=";", decimal=",",
                     header=0, names=["fecha", "hora", "valor", "_"], dtype={"fecha": str, "hora": str})
    df = df.dropna(subset=["valor"])
    if df.empty:
        return None, None
    u = df.iloc[-1]
    return float(u.valor), hora_sinca(u.fecha, u.hora)


def hora_sinca(fecha, hora):
    """'261121', '1000' → Timestamp en hora de Santiago."""
    return pd.Timestamp(f"20{fecha} {hora[:2]}:{hora[2:]}").tz_localize(TZ, ambiguous=True,
                                                                      nonexistent="shift_forward")


def sinca(timeout=30):
    filas = []
    for key, (nombre, lat, lon) in SINCA_ESTACIONES.items():
        try:
            temp, t = _sinca_ultima(key, "TEMP", timeout)
            hum, th = _sinca_ultima(key, "RHUM", timeout)
        except Exception as e:  # una estación caída no tumba a las demás
            print(f"SINCA {key}: {e}")
            continue
        if temp is None:
            continue
        filas.append({"source": f"SINCA_{key}", "lat": lat, "lon": lon, "temp_c": temp,
                      "humedad_pct": hum if th == t else float("nan"), "medido_en": t.tz_convert("UTC"),
                      "oficial": True, "bajo_techo": False})
    return _tabla(filas)


def _cargar_env(ruta=".env"):
    if os.path.exists(ruta):
        for linea in open(ruta):
            if "=" in linea and not linea.startswith("#"):
                k, v = linea.strip().split("=", 1)
                os.environ.setdefault(k, v)


def _num(texto):
    return float(texto.split()[0]) if texto else float("nan")


def _dmc_pedir(url, timeout):
    _cargar_env()
    usuario, token = os.getenv("DMC_USUARIO"), os.getenv("DMC_TOKEN")
    if not (usuario and token):
        raise RuntimeError("faltan DMC_USUARIO y DMC_TOKEN")
    r = requests.get(url, params={"usuario": usuario, "token": token}, timeout=timeout).json()
    if "datosEstaciones" not in r:
        raise RuntimeError(r.get("mensaje", "la DMC no trajo datosEstaciones"))
    return r


def dmc_estaciones(timeout=30):
    """Lecturas de la última hora (minuto a minuto) de las estaciones DMC de Santiago."""
    return dmc_tabla(_dmc_pedir(DMC_URL, timeout))


def dmc_12h(codigo, timeout=60):
    """Últimas 12 horas (minuto a minuto) de una estación DMC."""
    return dmc_tabla(_dmc_pedir(f"{DMC_EMA_URL}/{codigo}", timeout))


def dmc_tabla(r):
    """Respuesta de la DMC → tabla. datosEstaciones es una lista (red) o un objeto (una estación);
    una estación sin lecturas trae datos = null."""
    bloques = r["datosEstaciones"]
    if isinstance(bloques, dict):
        bloques = [bloques]
    filas = []
    for e in bloques:
        x = e["estacion"]
        lat, lon = float(x["latitud"]), float(x["longitud"])
        if not (-33.75 < lat < -33.2 and -71 < lon < -70.4):
            continue
        for d in e.get("datos") or []:
            if d.get("temperatura"):
                filas.append({"source": f"DMC_{x['codigoNacional']}", "lat": lat, "lon": lon,
                              "temp_c": _num(d["temperatura"]), "humedad_pct": _num(d.get("humedadRelativa")),
                              "medido_en": pd.Timestamp(d["momento"], tz="UTC"), "oficial": True, "bajo_techo": False})
    return _tabla(filas)


def dmc(timeout=30):
    """Última lectura con temperatura de cada estación DMC de Santiago."""
    h = dmc_estaciones(timeout)
    return h.sort_values("medido_en").groupby("source").tail(1).reset_index(drop=True)


FUENTES = {"sensor.community": sensor_community, "SINCA": sinca, "DMC": dmc}


def leer_todo():
    """Llama a cada fuente; si una falla sigue con las otras. Devuelve (tabla, errores)."""
    partes, errores = [], {}
    for nombre, f in FUENTES.items():
        try:
            partes.append(f())
        except Exception as e:
            errores[nombre] = repr(e)
    df = pd.concat([p for p in partes if len(p)], ignore_index=True) if any(len(p) for p in partes) else _tabla([])
    return df, errores
