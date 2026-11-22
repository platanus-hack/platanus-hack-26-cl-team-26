"""Aves por sonido con BirdNET (Cornell), sin red: el teléfono graba 15 s en WAV y aquí se identifican especies.

BirdNET usa la posición y la fecha para limitarse a las especies esperables en ese lugar y semana del año.
Modelo: BirdNET GLOBAL 6K V2.4 (K. Lisa Yang Center for Conservation Bioacoustics), licencia CC BY-NC-SA 4.0:
sirve para la hackathon (uso no comercial). Nombres comunes en inglés (el modelo no trae español); el nombre
científico siempre va.

Si birdnetlib o su motor no están instalados, disponible() es False: el audio se guarda igual y queda
«sin analizar». Que no se detecte un ave no significa que no haya.

Ruido de la calle: se graba caminando, con autos y gente; BirdNET aprendió de grabaciones de campo y tolera el
ruido de fondo, pero el tráfico fuerte tapa las aves lejanas y los arrullos graves (tórtolas). Por eso cada
escucha mide su ruido: energía entre 100 y 1500 Hz (donde está el tráfico), en dBFS por segundo, mediana y
máximo. Es una escala relativa del micrófono (no son dB calibrados y cambia entre teléfonos): bajo < −50,
medio hasta −38, alto sobre eso. Sin aves y con ruido alto, la escucha es «no concluyente».
"""
from __future__ import annotations

import contextlib
import io
import logging
import sys
import threading
import types
import wave
from datetime import datetime

import numpy as np

log = logging.getLogger(__name__)

MIN_CONF = 0.5          # confianza mínima de BirdNET para contar una detección
TASA_BIRDNET = 48000    # BirdNET trabaja a 48 kHz
MAX_SEGUNDOS = 200      # una escucha (15 s) o el audio de un recorrido en video (máx. 3 min)
BANDA_RUIDO = (100.0, 1500.0)
UMBRAL_BAJO, UMBRAL_ALTO = -50.0, -38.0   # dBFS de la banda de tráfico (relativo, sin calibrar)

_lock = threading.Lock()
_estado: dict = {"analizador": None, "error": None, "cargando": False}


def _motor_litert():
    """birdnetlib importa tflite_runtime (sin rueda para Python ≥ 3.12); ai-edge-litert es su sucesor liviano."""
    if "tflite_runtime.interpreter" in sys.modules:
        return
    try:
        from ai_edge_litert import interpreter as litert
    except ImportError:
        return  # birdnetlib intentará tensorflow.lite
    pkg = types.ModuleType("tflite_runtime")
    pkg.interpreter = litert
    sys.modules["tflite_runtime"] = pkg
    sys.modules["tflite_runtime.interpreter"] = litert


def _cargar():
    with _lock:
        if _estado["analizador"] is not None or _estado["error"]:
            return _estado["analizador"]
        try:
            _motor_litert()
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")  # pydub avisa que no hay ffmpeg: no lo usamos (WAV en memoria)
                from birdnetlib.analyzer import Analyzer
            with contextlib.redirect_stdout(io.StringIO()):  # birdnetlib imprime cada paso
                _estado["analizador"] = Analyzer()
            log.info("BirdNET cargado")
        except Exception as e:  # sin paquete, sin motor o modelo dañado: la app sigue sin aves por sonido
            _estado["error"] = f"{type(e).__name__}: {e}"
            log.warning("BirdNET no disponible (%s); el audio se guarda sin analizar", _estado["error"])
        return _estado["analizador"]


def precargar():
    """Carga el modelo en segundo plano (tarda unos segundos) para que la primera escucha no espere."""
    threading.Thread(target=_cargar, daemon=True).start()


def estado() -> str:
    """Para el mapa: «listo», «cargando» o «no disponible»."""
    if _estado["analizador"] is not None:
        return "listo"
    return "no disponible" if _estado["error"] else "cargando"


def disponible() -> bool:
    return _cargar() is not None


def ruido_por_segundo(x: np.ndarray, tasa: int) -> list[float]:
    """dBFS de la banda de tráfico (100–1500 Hz) en cada segundo de audio."""
    from scipy.signal import butter, sosfilt
    sos = butter(4, BANDA_RUIDO, btype="bandpass", fs=tasa, output="sos")
    y = sosfilt(sos, x.astype(np.float64))
    n = max(1, len(y) // tasa)
    return [round(float(20 * np.log10(np.sqrt(np.mean(t ** 2)) + 1e-9)), 1) for t in np.array_split(y, n)]


def nivel(db: float) -> str:
    return "bajo" if db < UMBRAL_BAJO else "medio" if db < UMBRAL_ALTO else "alto"


def resumir_ruido(dbs: list[float]) -> dict | None:
    """Mediana (el ruido de fondo, robusta a una bocina) y máximo, con su nivel."""
    if not dbs:
        return None
    med = round(float(np.median(dbs)), 1)
    return {"db": med, "max_db": round(float(max(dbs)), 1), "nivel": nivel(med)}


def concluyente(detecciones: list | None, ruido: dict | None) -> bool:
    """Sin aves y con ruido alto no se puede decir que no haya aves."""
    return bool(detecciones) or not ruido or ruido["nivel"] != "alto"


def leer_wav(datos: bytes) -> tuple[np.ndarray, int]:
    """WAV PCM 16 bit (lo que arma la página) → mono float32 en [-1, 1] y su tasa. Lanza ValueError si no sirve."""
    try:
        with wave.open(io.BytesIO(datos)) as w:
            canales, ancho, tasa, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
            if ancho != 2 or not 8000 <= tasa <= 96000 or n == 0:
                raise ValueError("WAV debe ser PCM de 16 bit entre 8 y 96 kHz")
            if n / tasa > MAX_SEGUNDOS:
                raise ValueError(f"Máximo {MAX_SEGUNDOS} s de audio")
            x = np.frombuffer(w.readframes(n), dtype="<i2").astype(np.float32) / 32768.0
    except (wave.Error, EOFError) as e:
        raise ValueError(f"No es un WAV válido: {e}") from e
    if canales > 1:
        x = x.reshape(-1, canales).mean(axis=1)
    return x, tasa


def detectar_crudo(x: np.ndarray, tasa: int, lat: float, lon: float, fecha: datetime | None = None) -> list[dict] | None:
    """Todas las detecciones (una por trozo de 3 s y especie), o None si BirdNET no está disponible."""
    a = _cargar()
    if a is None:
        return None
    if tasa != TASA_BIRDNET:
        import librosa
        x = librosa.resample(x, orig_sr=tasa, target_sr=TASA_BIRDNET)
    from birdnetlib import RecordingBuffer
    r = RecordingBuffer(a, x, TASA_BIRDNET, lat=lat, lon=lon, date=fecha or datetime.now(), min_conf=MIN_CONF)
    with _lock, contextlib.redirect_stdout(io.StringIO()):  # TFLite no es seguro entre hilos; birdnetlib imprime
        r.analyze()
    return [{"cientifico": d["scientific_name"], "comun": d["common_name"],
             "confianza": round(float(d["confidence"]), 3),
             "inicio_s": float(d["start_time"]), "fin_s": float(d["end_time"])} for d in r.detections]


def agrupar(crudas: list[dict]) -> list[dict]:
    """Una fila por especie: su mejor confianza (y ese momento)."""
    mejores: dict[str, dict] = {}
    for d in crudas:
        c = mejores.get(d["cientifico"])
        if c is None or d["confianza"] > c["confianza"]:
            mejores[d["cientifico"]] = d
    return sorted(mejores.values(), key=lambda d: -d["confianza"])


def detectar(datos: bytes, lat: float, lon: float, fecha: datetime | None = None) -> list[dict] | None:
    """Especies detectadas (una fila por especie, con su mejor confianza), o None si BirdNET no está
    disponible. Lanza ValueError si el audio no es un WAV válido."""
    x, tasa = leer_wav(datos)
    crudas = detectar_crudo(x, tasa, lat, lon, fecha)
    return None if crudas is None else agrupar(crudas)


def tramos_por_hexagono(track: list[dict], duracion_s: float, res: int = 9, min_s: float = 1.5) -> list[dict]:
    """Parte el audio de un recorrido según el hexágono donde iba el teléfono: cada cambio de hexágono corta a
    medio camino entre los dos puntos GPS. Devuelve [{h3_index, desde_s, hasta_s, lat, lon, precision_m}]."""
    import h3
    pts = sorted((p for p in track if p.get("t_s") is not None), key=lambda p: p["t_s"])
    if not pts:
        return []
    tramos: list[dict] = []
    for i, p in enumerate(pts):
        hx = h3.latlng_to_cell(p["lat"], p["lon"], res)
        desde = 0.0 if i == 0 else (pts[i - 1]["t_s"] + p["t_s"]) / 2
        if tramos and tramos[-1]["h3_index"] == hx:
            tramos[-1]["_pts"].append(p)
            continue
        if tramos:
            tramos[-1]["hasta_s"] = desde
        tramos.append({"h3_index": hx, "desde_s": desde, "hasta_s": duracion_s, "_pts": [p]})
    out = []
    for t in tramos:
        t["hasta_s"] = min(t["hasta_s"], duracion_s)
        if t["hasta_s"] - t["desde_s"] < min_s:
            continue
        ps = t.pop("_pts")
        medio = ps[len(ps) // 2]
        out.append({**t, "desde_s": round(t["desde_s"], 1), "hasta_s": round(t["hasta_s"], 1),
                    "lat": medio["lat"], "lon": medio["lon"], "precision_m": medio.get("precision_m")})
    return out
