"""Acciones personalizables y reglas "gesto -> accion".

Una ACCION es algo que pasa en el mundo fisico o digital:
  luz       prende, apaga o alterna la lampara/enchufe (ACTUATOR_ON_URL / OFF)
  decir     dice una frase por el parlante
  sonido    reproduce un archivo de audio
  media     controla la musica o el video del notebook (pausa, siguiente, volumen...)
  avisar    manda un mensaje al cuidador (ntfy o Telegram, configurado por el equipo)
  http      llama a una URL (enchufes, TV, Home Assistant...)        -> requiere aprobacion
  comando   ejecuta un programa en el notebook (adb, cec-client...)  -> requiere aprobacion

Una REGLA une un detector y un tipo de gesto con una accion:
  {"detector": "ceja", "gesto": "doble", "accion": "musica_siguiente"}

Las acciones http y comando que crea el agente quedan pendientes hasta que una
persona las aprueba en el panel. Todo se guarda en data/acciones.json.
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import re
import shutil
import time
from pathlib import Path
from typing import Awaitable, Callable

TYPES = ("luz", "decir", "sonido", "media", "avisar", "http", "comando")
NEEDS_APPROVAL = ("http", "comando")
MEDIA_COMMANDS = ("pausa", "siguiente", "anterior", "subir_volumen", "bajar_volumen", "silenciar")
# Gestos que entrega detectors.Bank: evento (inicio, corto, largo, doble, fin),
# ritmo (pausa, reanuda), estado ("estado:<etiqueta>") y trayectoria ("gesto:<etiqueta>").
GESTURES = ("inicio", "corto", "largo", "doble", "fin", "pausa", "reanuda")
_KIND_TO_GESTURE = {"start": "inicio", "short": "corto", "long": "largo", "double": "doble",
                    "end": "fin", "pause": "pausa", "resume": "reanuda"}
NAME_RE = re.compile(r"^[a-z0-9_]{1,40}$")

BUILTIN = {
    "luz_alternar": {"tipo": "luz", "modo": "alternar", "descripcion": "Alterna la lampara o enchufe"},
    "luz_prender": {"tipo": "luz", "modo": "prender", "descripcion": "Prende la lampara o enchufe"},
    "luz_apagar": {"tipo": "luz", "modo": "apagar", "descripcion": "Apaga la lampara o enchufe"},
    "musica_pausa": {"tipo": "media", "comando": "pausa", "descripcion": "Pausa o reanuda la musica/video"},
    "musica_siguiente": {"tipo": "media", "comando": "siguiente", "descripcion": "Siguiente cancion"},
    "musica_anterior": {"tipo": "media", "comando": "anterior", "descripcion": "Cancion anterior"},
    "volumen_subir": {"tipo": "media", "comando": "subir_volumen", "descripcion": "Sube el volumen"},
    "volumen_bajar": {"tipo": "media", "comando": "bajar_volumen", "descripcion": "Baja el volumen"},
}


class ActionError(ValueError):
    pass


def gesture_of(event: dict) -> str | None:
    """Traduce un evento de detectors.Bank al nombre de gesto de las reglas."""
    if event.get("kind") == "state":
        return f"estado:{event.get('state')}"
    if event.get("kind") == "trajectory":
        return f"gesto:{event['label']}" if event.get("label") else None
    return _KIND_TO_GESTURE.get(event.get("kind"))


def validate_action(name: str, spec: dict) -> dict:
    """Revisa y normaliza una accion. Devuelve la accion lista para guardar."""
    if not NAME_RE.match(name or ""):
        raise ActionError("el nombre debe ser minusculas, numeros o _ (max 40)")
    tipo = spec.get("tipo")
    if tipo not in TYPES:
        raise ActionError(f"tipo debe ser uno de {', '.join(TYPES)}")
    out = {"tipo": tipo, "descripcion": str(spec.get("descripcion", ""))[:200]}
    if tipo == "luz":
        if spec.get("modo") not in ("prender", "apagar", "alternar"):
            raise ActionError("luz necesita modo: prender, apagar o alternar")
        out["modo"] = spec["modo"]
    elif tipo == "decir":
        text = str(spec.get("texto", "")).strip()
        if not text:
            raise ActionError("decir necesita texto")
        out["texto"] = text[:300]
    elif tipo == "sonido":
        f = str(spec.get("archivo", "")).strip()
        if not f:
            raise ActionError("sonido necesita archivo (ruta o nombre dentro de sounds/)")
        out["archivo"] = f
    elif tipo == "media":
        if spec.get("comando") not in MEDIA_COMMANDS:
            raise ActionError(f"media necesita comando: {', '.join(MEDIA_COMMANDS)}")
        out["comando"] = spec["comando"]
    elif tipo == "avisar":
        msg = str(spec.get("mensaje", "")).strip()
        if not msg:
            raise ActionError("avisar necesita mensaje")
        out["mensaje"] = msg[:500]
    elif tipo == "http":
        url = str(spec.get("url", "")).strip()
        if not re.match(r"^https?://", url):
            raise ActionError("http necesita una url que empiece con http:// o https://")
        method = str(spec.get("metodo", "GET")).upper()
        if method not in ("GET", "POST", "PUT"):
            raise ActionError("metodo debe ser GET, POST o PUT")
        out.update(url=url, metodo=method)
        if spec.get("cuerpo") is not None:
            out["cuerpo"] = spec["cuerpo"]
    elif tipo == "comando":
        argv = spec.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
            raise ActionError("comando necesita argv: lista de textos, ej. [\"adb\", \"shell\", ...]")
        out["argv"] = argv[:30]
    return out


class Engine:
    """Catalogo de acciones, reglas y ejecucion."""

    def __init__(self, path: Path, lamp: Callable[[str], None] | None = None,
                 sounds_dir: Path | None = None):
        self.path = Path(path)
        self.lamp = lamp or (lambda mode: None)
        self.sounds_dir = sounds_dir
        self.actions: dict[str, dict] = {}
        self.rules: list[dict] = []
        self.log: list[dict] = []          # ultimas ejecuciones, para el panel
        self._watchers: list[asyncio.Queue] = []
        self._next_rule = 1
        self.load()

    # --- persistencia -----------------------------------------------------
    def load(self):
        data = {}
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                print(f"[acciones] no se pudo leer {self.path}: {e}")
        self.actions = {k: dict(v, aprobada=True, integrada=True) for k, v in BUILTIN.items()}
        for name, a in data.get("acciones", {}).items():
            if name not in BUILTIN:
                self.actions[name] = a
        self.rules = data.get("reglas", [])
        self._next_rule = 1 + max((r["id"] for r in self.rules), default=0)

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        custom = {k: v for k, v in self.actions.items() if not v.get("integrada")}
        self.path.write_text(json.dumps({"acciones": custom, "reglas": self.rules},
                                        indent=2, ensure_ascii=False), encoding="utf-8")

    # --- catalogo ---------------------------------------------------------
    def add_action(self, name: str, spec: dict, approved: bool | None = None) -> dict:
        if name in BUILTIN:
            raise ActionError(f"'{name}' es una accion integrada; usa otro nombre")
        a = validate_action(name, spec)
        a["aprobada"] = (a["tipo"] not in NEEDS_APPROVAL) if approved is None else approved
        self.actions[name] = a
        self.save()
        return a

    def approve(self, name: str) -> dict:
        a = self.actions.get(name)
        if a is None:
            raise ActionError(f"no existe la accion '{name}'")
        a["aprobada"] = True
        self.save()
        return a

    def remove_action(self, name: str):
        if name in BUILTIN:
            raise ActionError("las acciones integradas no se pueden borrar")
        self.actions.pop(name, None)
        self.rules = [r for r in self.rules if r["accion"] != name]
        self.save()

    # --- reglas -----------------------------------------------------------
    def add_rule(self, detector: str, gesture: str, action: str) -> dict:
        if action not in self.actions:
            raise ActionError(f"no existe la accion '{action}'")
        if gesture not in GESTURES and not gesture.startswith(("estado:", "gesto:")):
            raise ActionError(f"gesto debe ser {', '.join(GESTURES)}, estado:<etiqueta> "
                              "o gesto:<etiqueta> (detector de trayectoria)")
        for r in self.rules:
            if (r["detector"], r["gesto"], r["accion"]) == (detector, gesture, action):
                return r
        r = {"id": self._next_rule, "detector": detector, "gesto": gesture, "accion": action}
        self._next_rule += 1
        self.rules.append(r)
        self.save()
        return r

    def remove_rule(self, rule_id: int) -> bool:
        n = len(self.rules)
        self.rules = [r for r in self.rules if r["id"] != rule_id]
        self.save()
        return len(self.rules) < n

    def remove_rules_for(self, detector: str):
        self.rules = [r for r in self.rules if r["detector"] != detector]
        self.save()

    def has_rules(self, detector: str) -> bool:
        return any(r["detector"] == detector for r in self.rules)

    # --- eventos ----------------------------------------------------------
    def watch(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._watchers.append(q)
        return q

    def unwatch(self, q: asyncio.Queue):
        if q in self._watchers:
            self._watchers.remove(q)

    def handle(self, event: dict) -> list[str]:
        """Recibe un evento de un detector y lanza las acciones de sus reglas.

        Devuelve los nombres de las acciones lanzadas (se ejecutan en segundo plano).
        """
        for q in self._watchers:
            q.put_nowait(event)
        g = gesture_of(event)
        if g is None:
            return []
        fired = []
        for r in self.rules:
            if r["detector"] == event.get("detector") and r["gesto"] == g:
                fired.append(r["accion"])
                asyncio.get_running_loop().create_task(self.run(r["accion"], origin=r))
        return fired

    async def run(self, name: str, origin: dict | None = None) -> str:
        """Ejecuta una accion. Devuelve un texto corto con el resultado."""
        a = self.actions.get(name)
        if a is None:
            result = f"no existe la accion '{name}'"
        elif not a.get("aprobada"):
            result = f"'{name}' esta pendiente de aprobacion en el panel"
        else:
            try:
                result = await _execute(a, self)
            except Exception as e:  # noqa: BLE001 - una accion nunca bota el servidor
                result = f"fallo: {e}"
        self.log.append({"t": time.time(), "accion": name, "resultado": result,
                         "regla": origin["id"] if origin else None})
        del self.log[:-30]
        return result

    def status(self) -> dict:
        return {"acciones": self.actions, "reglas": self.rules, "log": self.log[-10:]}


# ---------------------------------------------------------------------------
# Ejecucion de cada tipo
# ---------------------------------------------------------------------------

async def _execute(a: dict, eng: Engine) -> str:
    t = a["tipo"]
    if t == "luz":
        eng.lamp(a["modo"])
        return f"luz: {a['modo']}"
    if t == "decir":
        from actuators import voice
        await voice.say(a["texto"])
        return f"dijo: {a['texto']}"
    if t == "sonido":
        from actuators import voice
        path = Path(a["archivo"])
        if not path.is_absolute() and eng.sounds_dir is not None:
            path = eng.sounds_dir / path
        if not path.exists():
            return f"no existe el archivo {path}"
        await voice.play(str(path))
        return f"sonando {path.name}"
    if t == "media":
        return await _media(a["comando"])
    if t == "avisar":
        return await _notify(a["mensaje"])
    if t == "http":
        import httpx
        async with httpx.AsyncClient(timeout=4.0) as c:
            kw = {}
            if "cuerpo" in a:
                kw["json" if isinstance(a["cuerpo"], (dict, list)) else "content"] = a["cuerpo"]
            r = await c.request(a["metodo"], a["url"], **kw)
        return f"http {r.status_code}"
    if t == "comando":
        p = await asyncio.create_subprocess_exec(
            *a["argv"], stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        _, err = await asyncio.wait_for(p.communicate(), timeout=10)
        return "ok" if p.returncode == 0 else f"salio con {p.returncode}: {err.decode()[:120]}"
    return "tipo desconocido"


async def _run(*argv: str) -> bool:
    p = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    return await asyncio.wait_for(p.wait(), timeout=5) == 0


async def _media(cmd: str) -> str:
    """Teclas multimedia del sistema: funciona con Spotify, YouTube, VLC..."""
    system = platform.system()
    if system == "Linux":
        if cmd in ("pausa", "siguiente", "anterior") and shutil.which("playerctl"):
            arg = {"pausa": "play-pause", "siguiente": "next", "anterior": "previous"}[cmd]
            return "ok" if await _run("playerctl", arg) else "playerctl fallo (¿hay musica abierta?)"
        if shutil.which("wpctl") and cmd in ("subir_volumen", "bajar_volumen", "silenciar"):
            args = {"subir_volumen": ["set-volume", "@DEFAULT_AUDIO_SINK@", "5%+"],
                    "bajar_volumen": ["set-volume", "@DEFAULT_AUDIO_SINK@", "5%-"],
                    "silenciar": ["set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"]}[cmd]
            return "ok" if await _run("wpctl", *args) else "wpctl fallo"
        return "falta playerctl o wpctl en el notebook"
    if system == "Windows":
        vk = {"pausa": 0xB3, "siguiente": 0xB0, "anterior": 0xB1,
              "subir_volumen": 0xAF, "bajar_volumen": 0xAE, "silenciar": 0xAD}[cmd]
        script = ("Add-Type -Name K -Namespace W -MemberDefinition '[DllImport(\"user32.dll\")]"
                  "public static extern void keybd_event(byte k,byte s,int f,int e);';"
                  f"[W.K]::keybd_event({vk},0,0,0);[W.K]::keybd_event({vk},0,2,0)")
        return "ok" if await _run("powershell", "-NoProfile", "-Command", script) else "fallo"
    if system == "Darwin":
        script = {"pausa": 'tell application "Music" to playpause',
                  "siguiente": 'tell application "Music" to next track',
                  "anterior": 'tell application "Music" to previous track',
                  "subir_volumen": "set volume output volume ((output volume of (get volume settings)) + 6)",
                  "bajar_volumen": "set volume output volume ((output volume of (get volume settings)) - 6)",
                  "silenciar": "set volume with output muted"}[cmd]
        return "ok" if await _run("osascript", "-e", script) else "fallo"
    return f"sistema {system} no soportado"


async def _notify(message: str) -> str:
    """Aviso al cuidador. El destino lo configura el equipo, no el agente:
    NTFY_TOPIC (app ntfy, sin cuenta) o TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID."""
    import httpx
    topic = os.environ.get("NTFY_TOPIC", "")
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    async with httpx.AsyncClient(timeout=5.0) as c:
        if token and chat:
            r = await c.post(f"https://api.telegram.org/bot{token}/sendMessage",
                             json={"chat_id": chat, "text": message})
            return f"telegram {r.status_code}"
        if topic:
            server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
            r = await c.post(f"{server}/{topic}", content=message.encode("utf-8"),
                             headers={"Title": "MagneSense", "Priority": "high"})
            return f"ntfy {r.status_code}"
    return "sin destino: definir NTFY_TOPIC o TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID"
