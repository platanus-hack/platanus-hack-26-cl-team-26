"""Lee sensores reales de Santiago cada 5 minutos y los graba (Rol 2).

Fuentes:
- Dirección Meteorológica de Chile (DMC), red de estaciones automáticas. Necesita usuario y token:
  variables de entorno DMC_USUARIO y DMC_TOKEN. Sin ellas se salta.
- sensor.community (sensores ciudadanos), sin registro.

Salidas:
- data/grabacion/AAAA-MM-DD.jsonl: todas las lecturas de cada ciclo, una por línea (para repetir el día).
- data/web_sensors.json: lecturas del último ciclo, con el formato de CONTRATO.md.

Uso: python web_sensors.py            (cada 5 min, sin parar)
     python web_sensors.py --una-vez
"""
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import h3
import requests

CENTRO = (-33.45, -70.65)
RADIO_KM = 20
INTERVALO_S = 300
TEMP_MIN, TEMP_MAX = -10, 45      # Santiago nunca ha llegado a 40 °C
MAX_ANTIGUEDAD_MIN = 60
MAX_SALTO_C = 3.0
DATA = Path(__file__).resolve().parent / "data"
GRABACION = DATA / "grabacion"

URL_DMC = "https://climatologia.meteochile.gob.cl/application/servicios/getDatosRecientesRedEma"
URL_SC = f"https://data.sensor.community/airrohr/v1/filter/area={CENTRO[0]},{CENTRO[1]},{RADIO_KM}"


def distancia_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


def numero(texto):
    """'20.2 °C' -> 20.2 ; None o '' -> None."""
    if texto is None:
        return None
    try:
        return float(str(texto).split()[0])
    except (ValueError, IndexError):
        return None


def iso_utc(texto):
    """'2026-11-21 15:18:35' (UTC) -> '2026-11-21T15:18:35+00:00'."""
    return datetime.strptime(texto, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).isoformat()


def lectura(source, lat, lon, temp_c, humedad_pct, timestamp):
    return {
        "source": source,
        "lat": lat,
        "lon": lon,
        "h3_index": h3.latlng_to_cell(lat, lon, 9),
        "temp_c": temp_c,
        "humedad_pct": humedad_pct,
        "timestamp": timestamp,
    }


def parsear_dmc(respuesta):
    """Última lectura con temperatura de cada estación a menos de RADIO_KM."""
    salida = []
    for bloque in respuesta.get("datosEstaciones", []):
        est = bloque["estacion"]
        lat, lon = float(est["latitud"]), float(est["longitud"])
        if distancia_km(*CENTRO, lat, lon) > RADIO_KM:
            continue
        datos = [d for d in bloque.get("datos", []) if numero(d.get("temperatura")) is not None]
        if not datos:
            continue
        d = max(datos, key=lambda d: d["momento"])
        salida.append(lectura(f"DMC_{est['codigoNacional']}", lat, lon, numero(d["temperatura"]),
                              numero(d.get("humedadRelativa")), iso_utc(d["momento"])))
    return salida


def parsear_sc(respuesta):
    """Última lectura con temperatura de cada ubicación de sensor.community (solo exteriores)."""
    ultimas = {}
    for x in respuesta:
        loc = x["location"]
        if str(loc.get("indoor")) == "1":
            continue
        valores = {v["value_type"]: v["value"] for v in x["sensordatavalues"]}
        temp = numero(valores.get("temperature"))
        if temp is None:
            continue
        previa = ultimas.get(loc["id"])
        if previa and previa["timestamp"] >= iso_utc(x["timestamp"]):
            continue
        ultimas[loc["id"]] = lectura(f"SC_{loc['id']}", float(loc["latitude"]), float(loc["longitude"]),
                                     temp, numero(valores.get("humidity")), iso_utc(x["timestamp"]))
    return list(ultimas.values())


def control_calidad(lecturas, previas, ahora):
    """Deja solo lecturas válidas.

    - Descarta temperaturas imposibles para Santiago (fuera de TEMP_MIN..TEMP_MAX).
    - Descarta lecturas con más de MAX_ANTIGUEDAD_MIN minutos (sensor sin datos recientes).
    - Descarta saltos bruscos: más de MAX_SALTO_C respecto de la lectura anterior del mismo sensor
      en los últimos 30 min (típico de un sensor que queda al sol).
    - Humedad fuera de 0..100 pasa a None (la temperatura sigue sirviendo).
    """
    anterior = {p["source"]: p for p in previas}
    validas = []
    for x in lecturas:
        if not TEMP_MIN <= x["temp_c"] <= TEMP_MAX:
            continue
        t = datetime.fromisoformat(x["timestamp"])
        if (ahora - t).total_seconds() > MAX_ANTIGUEDAD_MIN * 60:
            continue
        p = anterior.get(x["source"])
        if p and p["timestamp"] != x["timestamp"]:
            dt = (t - datetime.fromisoformat(p["timestamp"])).total_seconds()
            if 0 < dt <= 1800 and abs(x["temp_c"] - p["temp_c"]) > MAX_SALTO_C:
                continue
        h = x["humedad_pct"]
        validas.append({**x, "humedad_pct": h if h is not None and 0 <= h <= 100 else None})
    return validas


def indice_calor(temp_c, humedad_pct):
    """Sensación térmica (°C) con la fórmula de la NOAA (Rothfusz, con sus dos ajustes).

    Bajo 27 °C o sin humedad, la fórmula no aplica y se devuelve la temperatura.
    """
    if humedad_pct is None or temp_c < 27:
        return temp_c
    t = temp_c * 9 / 5 + 32
    rh = humedad_pct
    hi = (-42.379 + 2.04901523 * t + 10.14333127 * rh - 0.22475541 * t * rh - 0.00683783 * t * t
          - 0.05481717 * rh * rh + 0.00122874 * t * t * rh + 0.00085282 * t * rh * rh
          - 0.00000199 * t * t * rh * rh)
    if rh < 13 and 80 <= t <= 112:
        hi -= (13 - rh) / 4 * math.sqrt((17 - abs(t - 95)) / 17)
    elif rh > 85 and 80 <= t <= 87:
        hi += (rh - 85) / 10 * (87 - t) / 5
    return round((hi - 32) * 5 / 9, 1)


def leer_dmc():
    usuario, token = os.environ.get("DMC_USUARIO"), os.environ.get("DMC_TOKEN")
    if not usuario or not token:
        print("DMC: sin DMC_USUARIO/DMC_TOKEN, se salta")
        return []
    r = requests.get(URL_DMC, params={"usuario": usuario, "token": token}, timeout=60)
    r.raise_for_status()
    datos = r.json()
    if "datosEstaciones" not in datos:
        print("DMC:", datos.get("mensaje", "respuesta sin datos"))
        return []
    return parsear_dmc(datos)


def leer_sc():
    r = requests.get(URL_SC, timeout=60)
    r.raise_for_status()
    return parsear_sc(r.json())


def ciclo():
    lecturas = []
    for nombre, leer in (("DMC", leer_dmc), ("sensor.community", leer_sc)):
        try:
            nuevas = leer()
            print(f"{nombre}: {len(nuevas)} lecturas")
            lecturas += nuevas
        except (requests.RequestException, ValueError, KeyError) as e:
            print(f"{nombre}: error {e}")

    ahora = datetime.now(timezone.utc)
    GRABACION.mkdir(parents=True, exist_ok=True)
    with open(GRABACION / f"{ahora:%Y-%m-%d}.jsonl", "a", encoding="utf-8") as f:
        for x in lecturas:
            f.write(json.dumps({"leido": ahora.isoformat(), **x}) + "\n")

    salida = DATA / "web_sensors.json"
    previas = json.loads(salida.read_text(encoding="utf-8")) if salida.exists() else []
    validas = control_calidad(lecturas, previas, ahora)
    tmp = DATA / "web_sensors.json.tmp"
    tmp.write_text(json.dumps(validas, indent=1), encoding="utf-8")
    tmp.replace(DATA / "web_sensors.json")
    return validas


def main():
    una_vez = "--una-vez" in sys.argv
    while True:
        validas = ciclo()
        print(f"{datetime.now():%H:%M:%S} · {len(validas)} lecturas en web_sensors.json")
        if una_vez:
            break
        time.sleep(INTERVALO_S)


if __name__ == "__main__":
    main()
