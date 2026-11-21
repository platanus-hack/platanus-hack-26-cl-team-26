"""Actuador de voz: habla (o suena) por la salida de audio por defecto.

Si el parlante bluetooth esta conectado, PipeWire lo usa como salida por
defecto y la voz sale por ahi; si no, sale por el notebook (plan B).

Variables de entorno:
  VOICE=0            desactiva el actuador
  VOICE_ON="texto"   frase al encender (vacio = solo sonido)
  VOICE_OFF="texto"  frase al apagar
  VOICE_LANG=es      idioma de espeak-ng
"""
from __future__ import annotations

import asyncio
import os
import shutil

ENABLED = os.environ.get("VOICE", "1") != "0"
TEXT_ON = os.environ.get("VOICE_ON", "Lámpara encendida")
TEXT_OFF = os.environ.get("VOICE_OFF", "Lámpara apagada")
LANG = os.environ.get("VOICE_LANG", "es")
BEEP = "/usr/share/sounds/freedesktop/stereo/complete.oga"

_lock = asyncio.Lock()


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


async def on_lamp(on: bool):
    await say(TEXT_ON if on else TEXT_OFF)
