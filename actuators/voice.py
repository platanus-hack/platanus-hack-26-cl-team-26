"""Actuador de voz: habla (o suena) por la salida de audio por defecto.

Si el parlante bluetooth esta conectado, PipeWire lo usa como salida por
defecto y la voz sale por ahi; si no, sale por el notebook (plan B).

Variables de entorno:
  VOICE=0            desactiva el actuador
  VOICE_ON="texto"   frase al encender (vacio = solo sonido)
  VOICE_OFF="texto"  frase al apagar
  VOICE_LANG=es      idioma de espeak-ng
  SOUND_FILE=ruta    mp3/wav/ogg a reproducir al encender en vez de la voz.
                     Si no se define, usa el primer archivo en sounds/.
                     Al apagar la lampara la musica se corta.
"""
from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

ENABLED = os.environ.get("VOICE", "1") != "0"
TEXT_ON = os.environ.get("VOICE_ON", "Lámpara encendida")
TEXT_OFF = os.environ.get("VOICE_OFF", "Lámpara apagada")
LANG = os.environ.get("VOICE_LANG", "es")
BEEP = "/usr/share/sounds/freedesktop/stereo/complete.oga"

SOUNDS_DIR = Path(__file__).resolve().parent.parent / "sounds"

_lock = asyncio.Lock()
_music: asyncio.subprocess.Process | None = None


def sound_file() -> str | None:
    f = os.environ.get("SOUND_FILE")
    if f:
        return f if os.path.exists(f) else None
    if SOUNDS_DIR.is_dir():
        for p in sorted(SOUNDS_DIR.iterdir()):
            if p.suffix.lower() in (".mp3", ".wav", ".ogg", ".oga", ".flac", ".m4a"):
                return str(p)
    return None


def _command(text: str) -> list[str] | None:
    if text and shutil.which("spd-say"):
        return ["spd-say", "-w", "-l", LANG, text]
    if text and shutil.which("espeak-ng"):
        return ["espeak-ng", "-v", LANG, text]
    for player in ("pw-play", "paplay"):
        if shutil.which(player) and os.path.exists(BEEP):
            return [player, BEEP]
    return None


async def say(text: str):
    """Reproduce el texto sin bloquear el loop. Un mensaje a la vez."""
    cmd = _command(text)
    if not ENABLED or not cmd:
        return
    try:
        async with _lock:
            p = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await asyncio.wait_for(p.wait(), timeout=10)
    except Exception as e:  # noqa: BLE001 - la voz nunca bota el servidor
        print(f"[voz] fallo: {e}")


def stop_music():
    global _music
    if _music and _music.returncode is None:
        _music.terminate()
    _music = None


async def play(path: str):
    """Reproduce un archivo sin bloquear; corta el que estaba sonando."""
    global _music
    stop_music()
    if shutil.which("ffplay"):
        cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path]
    elif shutil.which("pw-play"):
        cmd = ["pw-play", path]
    else:
        return
    try:
        _music = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    except Exception as e:  # noqa: BLE001
        print(f"[voz] fallo al reproducir {path}: {e}")


async def on_lamp(on: bool):
    if not ENABLED:
        return
    song = sound_file()
    if song:
        if on:
            await play(song)
        else:
            stop_music()
        return
    await say(TEXT_ON if on else TEXT_OFF)
