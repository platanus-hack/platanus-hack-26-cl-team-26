"""Agente de MagneSense: arma detectores y los conecta a acciones conversando.

La persona graba sus ejemplos en la app o el panel (pasos 1 a 3). El agente:
  - crea el detector con esos ejemplos y revisa su calidad,
  - lo prueba en vivo pidiendo que haga el gesto,
  - lo conecta a acciones (luz, voz, musica, TV, aviso al cuidador...) y
    puede crear acciones nuevas; las de tipo http o comando quedan
    pendientes hasta que alguien las aprueba en el panel.

Usa el SDK de Anthropic (pip install anthropic) y la variable ANTHROPIC_API_KEY.
Sin clave o sin internet el resto del sistema funciona igual (plan B: panel).
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Awaitable, Callable

import analysis as analysis_mod
from actions import MEDIA_COMMANDS, TYPES, ActionError, Engine

# Cargar el SDK al iniciar: importarlo en el primer mensaje congela el servidor
# unos segundos (y en ese lapso no se procesan los datos del telefono).
try:
    import anthropic
except ImportError:          # sin SDK el agente queda "no disponible" y el resto funciona
    anthropic = None

MODEL = os.environ.get("AGENT_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("AGENT_EFFORT", "low")    # respuestas rapidas para la demo
MAX_STEPS = 16
COUNTDOWN_S = 3          # cuenta regresiva antes de cada intento de grabacion

SYSTEM = """Eres el asistente de MagneSense. MagneSense detecta movimientos muy pequenos del \
cuerpo con un iman pegado a la piel (dedo, ceja, musculo) y el magnetometro de un telefono, y los \
convierte en acciones fisicas. Lo usan personas con movilidad muy reducida (ELA, UCI, \
rehabilitacion), sus cuidadores y kinesiologos.

Tu trabajo: que la persona invente sus propios gestos y decida que hace cada uno.
1. Revisa con ver_estado si llegan datos del telefono y que ejemplos hay. Si la persona \
describe un movimiento nuevo, calibralo con grabar_ejemplos: 3 intentos por movimiento, con \
una instruccion que muestre el movimiento de forma visual y corta, con flechas, por ejemplo \
"Mueve el iman IZQUIERDA ➜ DERECHA" o "Mueve el iman DERECHA ➜ IZQUIERDA". Antes de grabar, \
pide dejar el telefono quieto y apoyado. Si un intento no se vio, repitelo o pide acercar el \
iman. (Los ejemplos tambien se pueden grabar desde la app o el panel.)
   Graba tambien, una vez, 4 intentos con la etiqueta "otros": movimientos que NO deben activar \
nada (instruccion: "Haz algo que NO sea el gesto: acerca el iman, muevelo recto, toca el \
celular"). Sin eso el gesto se puede activar con cualquier movimiento. Nunca crees un detector \
para "otros" ni lo conectes a una accion.
2. Elige el tipo de detector segun lo que importa del movimiento y crealo con crear_detector:
   - trayectoria: cuando importa el sentido u orden del movimiento (izquierda/derecha, subir/\
bajar, girar, un trazo). Una etiqueta por movimiento, grabadas por separado. Calidad buena: \
acierto 1.0 y separacion >= 2.
   - evento: un gesto o movimiento (contraccion, toque, giro, empujar hacia un lado). El \
servidor elige solo como reconocerlo (direccion o forma del movimiento, comparado con los \
otros grabados) y descarta ejemplos que no se vieron; si casi ninguno se vio, crear_detector \
devuelve el problema: explicalo y propone regrabar. Usa analizar_ejemplos para entender que \
vio el sensor.
   - estado: posiciones que se mantienen (abierta/cerrada). Calidad: separacion >= 2.
   - ritmo: algo periodico (respiracion, temblor).
   Explica la calidad en palabras simples; si es baja, propone regrabar.
3. Conecta gestos a acciones con conectar. Trayectoria entrega gesto:<etiqueta>. Evento entrega \
inicio (lo mas rapido), corto, largo (mas de 0,8 s), doble y fin; si un mismo detector usa \
varios, usa corto/largo/doble y no inicio. Estado entrega estado:<etiqueta>; ritmo entrega \
pausa y reanuda.
4. Usa las acciones que ya existen (listar_acciones) o crea nuevas con crear_accion: decir una \
frase, sonido, luz, media (musica/video del notebook), avisar al cuidador, http o comando.
5. Prueba siempre lo que armaste: ejecutar_accion para la accion y probar_detector para el \
gesto, y cuenta el resultado.

Reglas:
- Las acciones http y comando quedan pendientes hasta que una persona las aprueba en el panel. \
Dilo claramente y no digas que funcionan antes de probarlas aprobadas.
- No inventes direcciones IP, URLs ni comandos de equipos que no conoces: pregunta el modelo \
de TV o equipo y su IP. Ideas para la TV: Android TV o Google TV con adb (adb shell input \
keyevent ...), Chromecast con catt, HDMI-CEC con cec-client, Home Assistant con su API REST, \
o un enchufe/IR comercial con API local.
- Para frases de comunicacion (ELA), propone frases cortas y concretas segun lo que la \
persona necesita (sed, dolor, cambiar de posicion, llamar a alguien).
- Avisar al cuidador no reemplaza un sistema de emergencia; dilo si preguntan por emergencias. \
No hagas afirmaciones medicas.
- Responde en espanol de Chile, corto y claro (2 a 5 frases), sin markdown: tu respuesta se \
muestra en un panel y puede leerse en voz alta. Di que hiciste, no como lo hiciste por dentro."""


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required}


TOOLS = [
    {"name": "ver_estado",
     "description": "Muestra si llegan datos del telefono, el ruido, los ejemplos grabados por "
                    "etiqueta, los detectores, las acciones y las reglas. Usala al empezar y "
                    "cada vez que necesites saber que existe antes de crear o conectar algo.",
     "input_schema": _obj({}, [])},
    {"name": "grabar_ejemplos",
     "description": "Calibra un movimiento nuevo: muestra en pantalla (y dice) la instruccion, "
                    "hace una cuenta regresiva y graba cada intento. Usala cuando la persona "
                    "describe un movimiento que todavia no tiene ejemplos. Para movimientos con "
                    "sentido (izquierda/derecha) llamala una vez por cada sentido, con etiquetas "
                    "distintas. Devuelve si cada intento se vio y cuanto cambio el campo.",
     "input_schema": _obj({
         "etiqueta": {"type": "string", "description": "Nombre corto del movimiento, ej. izq_der."},
         "instruccion": {"type": "string",
                         "description": "Lo que se muestra en grande, visual y con flechas, "
                                        "ej. 'Mueve el iman IZQUIERDA ➜ DERECHA'."},
         "veces": {"type": "integer", "description": "Intentos, 3 por defecto (1 a 5)."},
         "segundos": {"type": "number", "description": "Duracion de cada intento, 3 por defecto (2 a 6)."},
         "reemplazar": {"type": "boolean",
                        "description": "Borrar antes los ejemplos con esa etiqueta (true por defecto)."},
     }, ["etiqueta", "instruccion"])},
    {"name": "analizar_ejemplos",
     "description": "Muestra que vio el sensor en cada ejemplo grabado: pico contra ruido, si se "
                    "vio, si quedo cortado o se movio el celular, que modelo conviene y si los "
                    "movimientos se distinguen entre si. Usala despues de grabar y antes de crear "
                    "un detector, y cuando algo no se reconoce bien.",
     "input_schema": _obj({}, [])},
    {"name": "crear_detector",
     "description": "Crea un detector a partir de los ejemplos grabados. tipo trayectoria: "
                    "movimientos donde importa el sentido u orden (usa etiquetas, una por "
                    "movimiento). tipo evento: un gesto (usa etiqueta). tipo estado: posiciones "
                    "distintas (usa etiquetas, al menos 2). tipo ritmo: algo periodico como la "
                    "respiracion (no necesita ejemplos). Devuelve la calidad.",
     "input_schema": _obj({
         "tipo": {"type": "string", "enum": ["trayectoria", "evento", "estado", "ritmo"]},
         "etiqueta": {"type": "string", "description": "Etiqueta de los ejemplos (evento)."},
         "etiquetas": {"type": "array", "items": {"type": "string"},
                       "description": "Etiquetas de cada movimiento (trayectoria) o posicion (estado)."},
         "nombre": {"type": "string", "description": "Nombre del detector; por defecto la etiqueta."},
         "banda": {"type": "string", "enum": ["respiracion", "temblor", "repeticion"],
                   "description": "Solo ritmo."},
         "pausa_s": {"type": "number", "description": "Solo ritmo: segundos sin ritmo para avisar pausa."},
         "duracion_minima_ms": {"type": "integer",
                                "description": "Solo evento: cuanto debe durar el gesto para contar "
                                               "(150 por defecto; 300 filtra movimientos involuntarios)."},
     }, ["tipo"])},
    {"name": "probar_detector",
     "description": "Prueba un detector en vivo: muestra y dice la instruccion, escucha durante "
                    "unos segundos y cuenta que gestos detecto. Usala despues de crear o conectar, "
                    "pidiendo un numero concreto de gestos para comparar.",
     "input_schema": _obj({
         "nombre": {"type": "string"},
         "segundos": {"type": "integer", "description": "Entre 3 y 30."},
         "instruccion": {"type": "string",
                         "description": "Lo que la persona debe hacer, ej. 'Haz el gesto corto 3 veces'."},
     }, ["nombre", "segundos", "instruccion"])},
    {"name": "listar_acciones",
     "description": "Lista las acciones disponibles (integradas y creadas), si estan aprobadas, "
                    "los sonidos disponibles y si el aviso al cuidador tiene destino configurado.",
     "input_schema": _obj({}, [])},
    {"name": "crear_accion",
     "description": "Crea una accion personalizada. Campos segun tipo: luz -> modo; decir -> texto; "
                    "sonido -> archivo; media -> comando; avisar -> mensaje; http -> url, metodo, "
                    "cuerpo; comando -> argv. Las de tipo http y comando quedan pendientes de "
                    "aprobacion en el panel.",
     "input_schema": _obj({
         "nombre": {"type": "string", "description": "minusculas_con_guion_bajo, ej. decir_tengo_sed"},
         "tipo": {"type": "string", "enum": list(TYPES)},
         "descripcion": {"type": "string", "description": "Para que sirve, en palabras simples."},
         "modo": {"type": "string", "enum": ["prender", "apagar", "alternar"]},
         "texto": {"type": "string"},
         "archivo": {"type": "string", "description": "Nombre dentro de sounds/ o ruta."},
         "comando": {"type": "string", "enum": list(MEDIA_COMMANDS)},
         "mensaje": {"type": "string"},
         "url": {"type": "string"},
         "metodo": {"type": "string", "enum": ["GET", "POST", "PUT"]},
         "cuerpo": {"type": "string", "description": "Cuerpo JSON o texto para POST/PUT."},
         "argv": {"type": "array", "items": {"type": "string"},
                  "description": "Programa y argumentos, ej. [\"adb\",\"shell\",\"input\",\"keyevent\",\"26\"]"},
     }, ["nombre", "tipo", "descripcion"])},
    {"name": "conectar",
     "description": "Crea una regla: cuando el detector entrega ese gesto, se ejecuta la accion. "
                    "Un detector puede tener varias reglas (corto, largo y doble distintos).",
     "input_schema": _obj({
         "detector": {"type": "string"},
         "gesto": {"type": "string",
                   "description": "gesto:<etiqueta> (trayectoria), inicio, corto, largo, doble, "
                                  "fin (evento), estado:<etiqueta>, pausa o reanuda (ritmo)"},
         "accion": {"type": "string"},
     }, ["detector", "gesto", "accion"])},
    {"name": "desconectar",
     "description": "Borra una regla por su id (lo ves en ver_estado).",
     "input_schema": _obj({"regla_id": {"type": "integer"}}, ["regla_id"])},
    {"name": "ejecutar_accion",
     "description": "Ejecuta una accion una vez, ahora, para probarla (por ejemplo antes de "
                    "conectarla a un gesto).",
     "input_schema": _obj({"accion": {"type": "string"}}, ["accion"])},
    {"name": "quitar_detector",
     "description": "Borra un detector y sus reglas. Pide confirmacion a la persona antes.",
     "input_schema": _obj({"nombre": {"type": "string"}}, ["nombre"])},
]

BANDS = {"respiracion": (0.1, 0.7), "temblor": (3.0, 12.0), "repeticion": (0.5, 3.0)}


# ---------------------------------------------------------------------------
# Modo plan: contrato con la app Android (android/SERVER_API.md)
# ---------------------------------------------------------------------------
# La app manda {"text", "context"} y espera en < 30 s {"reply", "steps"}. El
# servidor NO ejecuta nada: propone pasos y la app los hace cuando el cuidador
# toca "Hacer" (grabar, crear detector, enlazar a un dispositivo de la app).

PLAN_TIMEOUT_S = 25          # la app espera 30 s; responder antes con un error claro

PLAN_SYSTEM = """Eres el asistente de MagneSense dentro de la app Android. MagneSense detecta \
movimientos pequenos de un iman pegado al cuerpo (dedo, ceja, musculo) con el magnetometro del \
celular. Un cuidador te pide en lenguaje natural que un movimiento controle un dispositivo.

Tu respuesta es un plan de pasos que la app muestra con un boton "Hacer"; tu no ejecutas nada.
Pasos posibles:
- record: grabar ejemplos de un movimiento. label (nombre corto en minusculas, ej. "derecha"), \
count (5 para gestos, 3 por posicion para estados) y detector_type.
- train: crear el detector con esos ejemplos. detector_type y name. event: label y trigger \
("any" = apenas empieza, el mas rapido; "short", "long" (mas de 0,8 s) o "double"). state: \
labels (una por posicion, cada una grabada antes) y trigger = la posicion que activa. rhythm: \
band [min_hz, max_hz] (respiracion [0.1, 0.7], temblor [3, 12]) y pause_s; no necesita record.
- bind: enlazar el detector a un dispositivo: device es un id de context.devices, "scan" (abre \
el escaneo) o "none".

Como elegir:
- Cualquier movimiento (girar, barrer, empujar hacia un lado, un toque, una contraccion): \
detector_type "event" y trigger "any", con un detector por cada movimiento distinto (girar a \
la derecha y girar a la izquierda son dos). El servidor aprende solo como reconocerlo a partir \
de las grabaciones: por la direccion del empuje o por la forma completa del movimiento, \
comparandolo con los demas movimientos grabados, y descarta los ejemplos que no se vieron. \
Tu no eliges el algoritmo.
- Algo que queda en una posicion (abierto/cerrado, dedo estirado/recogido): state.
- Algo periodico (respiracion, temblor): rhythm.
- "Prender y apagar" con el mismo movimiento: un solo detector enlazado al dispositivo (la app \
alterna). Prender con uno y apagar con otro: dos detectores.
- No repitas pasos que ya estan hechos: revisa context.detectors, context.examples y \
context.bindings.
- Si el dispositivo pedido no esta en context.devices, no lo inventes: dilo en reply y usa "none".

Analisis de las grabaciones (campo "analisis", lo calcula el servidor con los datos reales):
- Si una etiqueta tiene "problema", el sensor no vio bien ese movimiento: NO propongas train \
para ella. En reply explica en palabras simples lo que paso (usa el problema y los avisos: \
iman muy lejos, celular movido, movimiento cortado) y propone record de nuevo, y despues \
train y bind.
- Si no tiene problema, se puede entrenar: propone train (si falta) y bind. Si hay avisos, \
mencionalos en una frase.
- Si "pares" muestra que dos movimientos se confunden, dilo y pide regrabarlos mas distintos.
- Si una etiqueta no aparece en el analisis, todavia no tiene ejemplos: empieza por record.

Contraejemplos "otros" (MUY importante para que el gesto no se active con cualquier cosa):
- Si analisis.hay_otros no es true, agrega SIEMPRE un paso record con label "otros", count 4 y \
detector_type "event", antes de los pasos train. En reply pide grabar 4 movimientos que NO deben \
activar nada, parecidos a lo que puede pasar sin querer: acercar el iman, moverlo recto a un \
lado y al otro, rascarse, tocar el celular.
- Nunca propongas train ni bind para "otros": el servidor los usa solo para comparar.
- Para cada intento del gesto pide: el celular apoyado sin tocarlo, siempre la misma distancia, \
y terminar volviendo a la posicion inicial. Si el analisis avisa "no volvio a su lugar" o "la \
fuerza cambia mucho", dilo en reply y propone regrabar.

reply: espanol de Chile, 1 a 3 frases cortas (se lee en voz alta), sin markdown. Explica que \
hacer: por ejemplo "Graba 5 veces el giro a la derecha y despues toca Hacer en cada paso."
Llena con null los campos que un paso no usa."""

_NULLABLE_STR = {"anyOf": [{"type": "string"}, {"type": "null"}]}
PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["reply", "steps"],
    "properties": {
        "reply": {"type": "string"},
        "steps": {"type": "array", "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["type", "label", "count", "detector_type", "name", "trigger", "labels",
                         "band", "pause_s", "detector", "device"],
            "properties": {
                "type": {"type": "string", "enum": ["record", "train", "bind"]},
                "label": _NULLABLE_STR,
                "count": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                "detector_type": {"anyOf": [{"type": "string", "enum": ["event", "state", "rhythm"]},
                                            {"type": "null"}]},
                "name": _NULLABLE_STR,
                "trigger": _NULLABLE_STR,
                "labels": {"anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "null"}]},
                "band": {"anyOf": [{"type": "array", "items": {"type": "number"}}, {"type": "null"}]},
                "pause_s": {"anyOf": [{"type": "number"}, {"type": "null"}]},
                "detector": _NULLABLE_STR,
                "device": _NULLABLE_STR,
            },
        }},
    },
}


def clean_steps(steps: list, context: dict) -> list[dict]:
    """Quita nulls y descarta pasos incompletos, para que la app no reciba basura."""
    devices = {str(d.get("id")) for d in context.get("devices", []) if isinstance(d, dict)}
    out = []
    for s in steps if isinstance(steps, list) else []:
        if not isinstance(s, dict):
            continue
        s = {k: v for k, v in s.items() if v is not None}
        t = s.get("type")
        target = s.get("label") or s.get("name") or s.get("detector") or ""
        if t in ("train", "bind") and analysis_mod.is_negative(target):
            continue                  # "otros" son contraejemplos: nunca se entrenan ni enlazan
        if t == "record":
            if not s.get("label"):
                continue
            s["count"] = max(1, min(10, int(s.get("count") or 5)))
            s.setdefault("detector_type", "event")
        elif t == "train":
            kind = s.get("detector_type")
            if kind == "event" and not s.get("label"):
                continue
            if kind == "state" and len(s.get("labels") or []) < 2:
                continue
            if kind not in ("event", "state", "rhythm") or not s.get("name"):
                continue
            if kind == "event" and s.get("trigger") not in ("any", "short", "long", "double"):
                s["trigger"] = "any"
        elif t == "bind":
            if not s.get("detector"):
                continue
            if s.get("device") not in devices | {"scan", "none"}:
                s["device"] = "none"
        else:
            continue
        out.append(s)
    return out


class Context:
    """Lo que el agente necesita del servidor (se pasa desde server.py)."""

    def __init__(self, engine: Engine, status: Callable[[], dict],
                 train: Callable[[dict], Awaitable[dict]],
                 remove_detector: Callable[[str], Awaitable[None]],
                 broadcast: Callable[[dict], Awaitable[None]],
                 say: Callable[[str], Awaitable[None]] | None = None,
                 sounds: Callable[[], list[str]] | None = None,
                 record_start: Callable[[str], None] | None = None,
                 record_stop: Callable[[], Awaitable[dict]] | None = None,
                 clear_examples: Callable[[str], None] | None = None,
                 analysis: Callable[[], dict] | None = None):
        self.engine = engine
        self.status = status
        self.train = train
        self.remove_detector = remove_detector
        self.broadcast = broadcast
        self.say = say
        self.sounds = sounds or (lambda: [])
        self.record_start = record_start
        self.record_stop = record_stop
        self.clear_examples = clear_examples
        self.analysis = analysis


class Agent:
    def __init__(self, ctx: Context, client=None):
        self.ctx = ctx
        self.messages: list = []
        self.lock = asyncio.Lock()
        self._client = client

    # --- cliente ----------------------------------------------------------
    def unavailable_reason(self) -> str | None:
        if self._client is not None:
            return None
        if anthropic is None:
            return "falta instalar el SDK: pip install anthropic"
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            return "falta la variable ANTHROPIC_API_KEY en el notebook del servidor"
        return None

    def client(self):
        if self._client is None:
            self._client = anthropic.AsyncAnthropic()
        return self._client

    def reset(self):
        self.messages = []

    async def plan(self, text: str, context: dict) -> dict:
        """Modo app Android: una sola llamada, devuelve {"reply", "steps"} o {"error"}."""
        reason = self.unavailable_reason()
        if reason:
            return {"error": f"El asistente no esta disponible: {reason}"}
        payload = {"pedido": text, "context": context}
        if self.ctx.analysis is not None:
            try:
                payload["analisis"] = analysis_mod.summary(self.ctx.analysis())
            except Exception as e:  # noqa: BLE001 - sin analisis igual se puede planificar
                payload["analisis"] = {"error": str(e)}
        user = json.dumps(payload, ensure_ascii=False)
        try:
            resp = await asyncio.wait_for(
                self.client().beta.messages.create(
                    model=MODEL, max_tokens=4000, system=PLAN_SYSTEM,
                    messages=[{"role": "user", "content": user}],
                    output_config={"effort": EFFORT,
                                   "format": {"type": "json_schema", "schema": PLAN_SCHEMA}},
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                ),
                timeout=PLAN_TIMEOUT_S)
        except asyncio.TimeoutError:
            return {"error": "El asistente tardo demasiado. Intenta de nuevo con un pedido mas corto."}
        except Exception as e:  # noqa: BLE001
            if anthropic is not None and isinstance(e, anthropic.AuthenticationError):
                return {"error": "La ANTHROPIC_API_KEY del servidor no es valida."}
            if anthropic is not None and isinstance(e, anthropic.RateLimitError):
                return {"error": "Limite de uso de la API; espera unos segundos."}
            if anthropic is not None and isinstance(e, anthropic.APIConnectionError):
                return {"error": "El servidor no tiene conexion a internet."}
            return {"error": f"Fallo el asistente ({type(e).__name__})."}
        if resp.stop_reason == "refusal":
            return {"error": "No puedo ayudar con ese pedido."}
        if resp.stop_reason == "max_tokens":
            return {"error": "La respuesta quedo cortada; intenta de nuevo."}
        try:
            data = json.loads(_text(resp))
        except json.JSONDecodeError:
            return {"error": "El asistente respondio en un formato inesperado."}
        return {"reply": str(data.get("reply", "")).strip() or "Listo.",
                "steps": clean_steps(data.get("steps"), context)}

    # --- conversacion -----------------------------------------------------
    async def chat(self, text: str) -> str:
        reason = self.unavailable_reason()
        if reason:
            return f"El agente no esta disponible: {reason}. Puedes usar los botones del panel."
        async with self.lock:
            n_before = len(self.messages)
            self.messages.append({"role": "user", "content": text})
            try:
                return await self._loop()
            except Exception as e:  # noqa: BLE001
                # Dejar el historial como estaba para no romper la siguiente pregunta
                del self.messages[n_before:]
                return f"No pude responder ({type(e).__name__}: {e}). Intenta de nuevo."

    async def _loop(self) -> str:
        for _ in range(MAX_STEPS):
            try:
                resp = await self.client().beta.messages.create(
                    model=MODEL, max_tokens=16000, system=SYSTEM, tools=TOOLS,
                    messages=self.messages,
                    output_config={"effort": EFFORT},
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                )
            except anthropic.AuthenticationError:
                raise RuntimeError("la ANTHROPIC_API_KEY no es valida")
            except anthropic.RateLimitError:
                raise RuntimeError("limite de uso de la API, espera unos segundos")
            except anthropic.APIConnectionError:
                raise RuntimeError("sin conexion a internet")

            self.messages.append({"role": "assistant", "content": resp.content})
            if resp.stop_reason == "refusal":
                return "No puedo ayudar con eso. Prueba pidiendolo de otra forma."
            if resp.stop_reason == "pause_turn":
                continue
            if resp.stop_reason == "max_tokens":
                return _text(resp) or "La respuesta quedo cortada; pregunta de nuevo."
            calls = [b for b in resp.content if b.type == "tool_use"]
            if resp.stop_reason != "tool_use" or not calls:
                return _text(resp) or "Listo."
            note = _text(resp)
            if note:
                await self.ctx.broadcast({"type": "agent", "role": "assistant", "text": note,
                                          "partial": True})
            results = []
            for b in calls:
                await self.ctx.broadcast({"type": "agent", "role": "tool", "name": b.name,
                                          "input": b.input})
                try:
                    out = await self.run_tool(b.name, b.input if isinstance(b.input, dict) else {})
                    results.append({"type": "tool_result", "tool_use_id": b.id,
                                    "content": json.dumps(out, ensure_ascii=False)})
                except (ActionError, ValueError, KeyError, TypeError) as e:
                    results.append({"type": "tool_result", "tool_use_id": b.id,
                                    "content": f"Error: {e}", "is_error": True})
            self.messages.append({"role": "user", "content": results})
        return "Me tome demasiados pasos; dime en que seguimos."

    # --- herramientas -----------------------------------------------------
    async def run_tool(self, name: str, inp: dict):
        eng = self.ctx.engine
        if name == "ver_estado":
            s = self.ctx.status()
            age = time.time() - s["last_rx"] if s.get("last_rx") else None
            return {
                "telefono": "enviando datos" if age is not None and age < 2 else "sin datos ahora",
                "muestreo_hz": s.get("rate"), "ruido_uT": s.get("noise"),
                "ejemplos": s.get("examples", {}),
                "detectores": [{k: d.get(k) for k in ("name", "type", "count", "last", "state", "labels")
                                if d.get(k) is not None}
                               for d in s.get("phase2", {}).get("detectors", [])],
                "reglas": eng.rules,
                "acciones": sorted(eng.actions),
            }
        if name == "analizar_ejemplos":
            if self.ctx.analysis is None:
                raise ValueError("este servidor no tiene analisis de ejemplos")
            return analysis_mod.summary(self.ctx.analysis())
        if name == "grabar_ejemplos":
            return await self._record(inp)
        if name == "crear_detector":
            return await self._create_detector(inp)
        if name == "probar_detector":
            return await self._probe(inp)
        if name == "listar_acciones":
            return {
                "acciones": {k: {"tipo": a["tipo"], "descripcion": a.get("descripcion", ""),
                                 "aprobada": a.get("aprobada", False)} for k, a in eng.actions.items()},
                "sonidos": self.ctx.sounds(),
                "aviso_cuidador_configurado": bool(os.environ.get("NTFY_TOPIC") or (
                    os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))),
            }
        if name == "crear_accion":
            spec = {k: v for k, v in inp.items() if k != "nombre"}
            if isinstance(spec.get("cuerpo"), str):
                try:
                    spec["cuerpo"] = json.loads(spec["cuerpo"])
                except json.JSONDecodeError:
                    pass
            a = eng.add_action(inp["nombre"], spec)
            if not a["aprobada"]:
                await self.ctx.broadcast({"type": "info",
                                          "text": f"Accion '{inp['nombre']}' pendiente de aprobacion"})
                await self.ctx.broadcast({"type": "rules", **eng.status()})
                return {"creada": inp["nombre"], "estado": "pendiente de aprobacion en el panel"}
            await self.ctx.broadcast({"type": "rules", **eng.status()})
            return {"creada": inp["nombre"], "estado": "lista"}
        if name == "conectar":
            dets = self._detector_names()
            if inp["detector"] not in dets:
                raise ValueError(f"no existe el detector '{inp['detector']}'. Hay: {', '.join(dets) or 'ninguno'}")
            r = eng.add_rule(inp["detector"], inp["gesto"], inp["accion"])
            await self.ctx.broadcast({"type": "rules", **eng.status()})
            a = eng.actions[inp["accion"]]
            return {"regla": r, "aviso": None if a.get("aprobada") else
                    "la accion esta pendiente de aprobacion: no se ejecutara hasta aprobarla"}
        if name == "desconectar":
            ok = eng.remove_rule(int(inp["regla_id"]))
            await self.ctx.broadcast({"type": "rules", **eng.status()})
            return {"borrada": ok}
        if name == "ejecutar_accion":
            return {"resultado": await eng.run(inp["accion"])}
        if name == "quitar_detector":
            await self.ctx.remove_detector(inp["nombre"])
            eng.remove_rules_for(inp["nombre"])
            await self.ctx.broadcast({"type": "rules", **eng.status()})
            return {"borrado": inp["nombre"]}
        raise ValueError(f"herramienta desconocida: {name}")

    def _detector_names(self) -> list[str]:
        return [d["name"] for d in self.ctx.status().get("phase2", {}).get("detectors", [])]

    async def _create_detector(self, inp: dict) -> dict:
        tipo = inp["tipo"]
        labels: list[str] = []
        if tipo == "trayectoria":
            labels = inp.get("etiquetas") or ([inp["etiqueta"]] if inp.get("etiqueta") else [])
            if not labels:
                raise ValueError("falta etiquetas (una por movimiento)")
            cfg = {"type": "trajectory", "labels": labels, "name": inp.get("nombre") or "movimiento"}
        elif tipo == "evento":
            label = inp.get("etiqueta")
            if not label:
                raise ValueError("falta etiqueta")
            cfg = {"type": "event", "label": label, "name": inp.get("nombre") or label,
                   "min_on_ms": int(inp.get("duracion_minima_ms") or 150)}
        elif tipo == "estado":
            labels = inp.get("etiquetas") or []
            if len(labels) < 2:
                raise ValueError("un detector de estado necesita al menos 2 etiquetas")
            cfg = {"type": "state", "labels": labels, "name": inp.get("nombre") or "estado"}
        elif tipo == "ritmo":
            band = inp.get("banda", "respiracion")
            cfg = {"type": "rhythm", "name": inp.get("nombre") or band, "band": list(BANDS[band]),
                   "pause_s": float(inp.get("pausa_s") or 10)}
        else:
            raise ValueError("tipo debe ser evento, estado o ritmo")
        cfg["action"] = "none"          # las acciones las deciden las reglas
        out = await self.ctx.train(cfg)
        info = out.get("info", {})
        res = {"detector": out.get("detector"), "tipo": tipo}
        if "consistency" in info:
            c = info["consistency"]
            res["parecido_entre_ejemplos"] = c
            res["calidad"] = "buena" if c >= 0.8 else "baja: conviene regrabar los ejemplos"
        if "separation" in info:
            s = info["separation"]
            res["separacion"] = s
            res["calidad"] = "buena" if s >= 2 else "baja: las posiciones se parecen mucho"
        if "acierto_dejando_uno_fuera" in info:
            acc, sep = info["acierto_dejando_uno_fuera"], info.get("separacion")
            res.update(acierto=acc, separacion=sep, ejemplos=info.get("ejemplos"),
                       gestos=[f"gesto:{lab}" for lab in labels])
            res["calidad"] = ("buena" if acc == 1.0 and (sep is None or sep >= 2) else
                              "baja: los movimientos se confunden; conviene regrabar con "
                              "movimientos mas claros y siempre a la misma distancia")
        return res

    async def _record(self, inp: dict) -> dict:
        ctx = self.ctx
        if ctx.record_start is None or ctx.record_stop is None:
            raise ValueError("este servidor no permite grabar desde el agente")
        label = str(inp["etiqueta"]).strip()[:40]
        text = str(inp["instruccion"])[:160]
        n = max(1, min(5, int(inp.get("veces") or 3)))
        secs = max(2.0, min(6.0, float(inp.get("segundos") or 3)))
        s = ctx.status()
        if not s.get("last_rx") or time.time() - s["last_rx"] > 2:
            return {"error": "no llegan datos del telefono; revisa que la app este transmitiendo"}
        if s.get("phase2", {}).get("calibrating") or s.get("calibrating"):
            return {"error": "el sistema esta calibrando; espera 2 s con el telefono quieto"}
        if inp.get("reemplazar", True) and ctx.clear_examples:
            ctx.clear_examples(label)
        noise = float(s.get("phase2", {}).get("noise") or s.get("noise") or 0.2)
        thr = max(6 * noise, 1.0)
        attempts = []
        try:
            for i in range(1, n + 1):
                tag = f"{text}  ·  intento {i} de {n}"
                if COUNTDOWN_S > 0:
                    await ctx.broadcast({"type": "probe", "phase": "prep", "seconds": COUNTDOWN_S,
                                         "text": f"Preparate: {tag}"})
                    if ctx.say:
                        asyncio.create_task(ctx.say(f"Intento {i}. Preparate"))
                    await asyncio.sleep(COUNTDOWN_S)
                ctx.record_start(label)
                await ctx.broadcast({"type": "probe", "phase": "rec", "seconds": int(round(secs)),
                                     "text": f"AHORA: {tag}"})
                if ctx.say:
                    asyncio.create_task(ctx.say("Ahora"))
                await asyncio.sleep(secs)
                out = await ctx.record_stop()
                ex = out.get("example")
                peak = float(max((sum(v * v for v in d) ** 0.5 for d in ex["delta"]), default=0.0)) \
                    if ex is not None else 0.0
                attempts.append({"intento": i, "pico_uT": round(peak, 2), "se_vio": peak > thr})
        finally:
            await ctx.broadcast({"type": "probe", "text": "", "seconds": 0})
        total = ctx.status().get("examples", {}).get(label, 0)      # {etiqueta: cantidad}
        return {"etiqueta": label, "intentos": attempts, "ejemplos_guardados": total,
                "umbral_uT": round(thr, 2),
                "aviso": None if all(a["se_vio"] for a in attempts) else
                "algun intento no se vio: repitelo o pide acercar el iman al telefono"}

    async def _probe(self, inp: dict) -> dict:
        name = inp["nombre"]
        if name not in self._detector_names():
            raise ValueError(f"no existe el detector '{name}'")
        secs = max(3, min(30, int(inp.get("segundos", 8))))
        text = str(inp.get("instruccion", "Haz el gesto"))[:200]
        s = self.ctx.status()
        if not s.get("last_rx") or time.time() - s["last_rx"] > 2:
            return {"error": "no llegan datos del telefono; revisa que la app este transmitiendo"}
        q = self.ctx.engine.watch()
        try:
            await self.ctx.broadcast({"type": "probe", "text": text, "seconds": secs})
            if self.ctx.say:
                asyncio.create_task(self.ctx.say(text))
            seen: list[dict] = []
            end = time.monotonic() + secs
            while (left := end - time.monotonic()) > 0:
                try:
                    e = await asyncio.wait_for(q.get(), timeout=left)
                except asyncio.TimeoutError:
                    break
                if e.get("detector") == name:
                    seen.append(e)
        finally:
            self.ctx.engine.unwatch(q)
            await self.ctx.broadcast({"type": "probe", "text": "", "seconds": 0})
        counts: dict[str, int] = {}
        for e in seen:
            k = e.get("kind")
            if k == "state":
                k = f"estado:{e.get('state')}"
            counts[k] = counts.get(k, 0) + 1
        names = {"start": "inicio", "short": "corto", "long": "largo", "double": "doble",
                 "end": "fin", "drift": "deriva_ignorada", "stuck": "iman_quieto_mucho_rato",
                 "pause": "pausa", "resume": "reanuda"}
        return {"segundos": secs,
                "gestos_detectados": {names.get(k, k): v for k, v in counts.items()},
                "total_gestos": sum(v for k, v in counts.items() if k in ("short", "long", "double")
                                    or k.startswith("estado:") or k == "pause")}


def _text(resp) -> str:
    return "\n".join(b.text for b in resp.content if b.type == "text").strip()
