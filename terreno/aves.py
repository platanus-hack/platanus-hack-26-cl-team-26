"""Aves por sonido con BirdNET (Cornell), sin red: el teléfono graba 15 s en WAV y aquí se identifican especies.

BirdNET usa la posición y la fecha para limitarse a las especies esperables en ese lugar y semana del año.
Modelo: BirdNET GLOBAL 6K V2.4 (K. Lisa Yang Center for Conservation Bioacoustics), licencia CC BY-NC-SA 4.0:
sirve para la hackathon (uso no comercial). Nombres comunes en inglés (el modelo no trae español); el nombre
científico siempre va.

Si birdnetlib o su motor no están instalados, disponible() es False: el audio se guarda igual y queda
«sin analizar». Que no se detecte un ave no significa que no haya.
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
MAX_SEGUNDOS = 60

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


def detectar(datos: bytes, lat: float, lon: float, fecha: datetime | None = None) -> list[dict] | None:
    """Especies detectadas (una fila por especie, con su mejor confianza y primer momento), o None si BirdNET
    no está disponible. Lanza ValueError si el audio no es un WAV válido."""
    x, tasa = leer_wav(datos)
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
    mejores: dict[str, dict] = {}
    for d in r.detections:
        c = mejores.get(d["scientific_name"])
        if c is None or d["confidence"] > c["confianza"]:
            mejores[d["scientific_name"]] = {
                "cientifico": d["scientific_name"], "comun": d["common_name"],
                "confianza": round(float(d["confidence"]), 3),
                "inicio_s": float(d["start_time"]), "fin_s": float(d["end_time"]),
            }
    return sorted(mejores.values(), key=lambda d: -d["confianza"])
