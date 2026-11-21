"""Pruebas de la fase 3: acciones, reglas y agente.

El modelo de lenguaje se reemplaza por respuestas guionadas, asi que no se
llama a la API ni se gasta nada: se valida el codigo, no la conversacion real.
"""
import asyncio
import json
import os
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import server
from actions import ActionError, Engine
from agent import Agent, Context
from test_server import batch

T0 = 1_700_000_000.0


def tmp_engine(lamp=None):
    return Engine(Path(tempfile.mkdtemp()) / "acciones.json", lamp=lamp)


# --- motor de acciones -------------------------------------------------------

def test_validation_approval_and_persistence():
    eng = tmp_engine()
    a = eng.add_action("decir_sed", {"tipo": "decir", "texto": "Tengo sed"})
    assert a["aprobada"] is True                                  # decir no requiere aprobacion
    h = eng.add_action("tv_apagar", {"tipo": "http", "url": "http://192.168.1.50/off"})
    assert h["aprobada"] is False                                 # http si
    c = eng.add_action("tv_adb", {"tipo": "comando", "argv": ["adb", "shell", "input", "keyevent", "26"]})
    assert c["aprobada"] is False
    for bad in [("X mal", {"tipo": "decir", "texto": "a"}),
                ("ok", {"tipo": "decir"}),
                ("ok", {"tipo": "http", "url": "ftp://x"}),
                ("ok", {"tipo": "comando", "argv": "rm -rf /"}),
                ("ok", {"tipo": "nada"}),
                ("luz_prender", {"tipo": "decir", "texto": "a"})]:
        with pytest.raises(ActionError):
            eng.add_action(*bad)
    assert "pendiente" in asyncio.run(eng.run("tv_apagar"))      # no se ejecuta sin aprobar
    eng.approve("tv_apagar")
    eng.add_rule("ceja", "corto", "decir_sed")
    again = Engine(eng.path)                                      # se recupera del disco
    assert again.actions["tv_apagar"]["aprobada"] is True
    assert again.actions["decir_sed"]["texto"] == "Tengo sed"
    assert again.rules[0]["gesto"] == "corto"
    assert "luz_prender" in again.actions                         # integradas siempre estan
    with pytest.raises(ActionError):
        eng.add_rule("ceja", "guino", "decir_sed")                # gesto invalido
    with pytest.raises(ActionError):
        eng.add_rule("ceja", "corto", "no_existe")


def test_rules_fire_by_gesture():
    modes = []
    eng = tmp_engine(lamp=modes.append)
    eng.add_rule("ceja", "corto", "luz_prender")
    eng.add_rule("ceja", "largo", "luz_apagar")
    eng.add_rule("puerta", "estado:abierta", "luz_alternar")

    async def go():
        q = eng.watch()
        assert eng.handle({"detector": "ceja", "kind": "start"}) == []
        assert eng.handle({"detector": "ceja", "kind": "short"}) == ["luz_prender"]
        assert eng.handle({"detector": "otro", "kind": "short"}) == []
        assert eng.handle({"detector": "ceja", "kind": "long"}) == ["luz_apagar"]
        assert eng.handle({"detector": "puerta", "kind": "state", "state": "abierta"}) == ["luz_alternar"]
        await asyncio.sleep(0.05)
        assert q.qsize() == 5                                     # la prueba en vivo ve todo
        eng.unwatch(q)

    asyncio.run(go())
    assert modes == ["prender", "apagar", "alternar"]
    assert [x["accion"] for x in eng.log] == ["luz_prender", "luz_apagar", "luz_alternar"]


# --- agente de punta a punta con el servidor ---------------------------------

def block_text(t):
    return SimpleNamespace(type="text", text=t)


def block_tool(i, name, inp):
    return SimpleNamespace(type="tool_use", id=f"tu_{i}", name=name, input=inp)


class FakeClient:
    """Devuelve respuestas guionadas y guarda lo que recibio."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    async def _create(self, **kw):
        self.calls.append(json.loads(json.dumps(kw["messages"], default=lambda o: o.__dict__)))
        content, stop = self.turns.pop(0)
        return SimpleNamespace(content=content, stop_reason=stop)


def fresh_server():
    server.DATA_DIR = Path(tempfile.mkdtemp())
    server.det.reset()
    server.bank.detectors.clear()
    server.bank.pipeline.reset()
    server.examples.clear()
    server.state.update(csv_writer=None, first_saved=False, last_rx=None)
    server.engine.path = server.DATA_DIR / "acciones.json"
    server.engine.load()
    server.engine.log.clear()
    server.assistant.reset()
    return TestClient(server.app)


class Clock:
    def __init__(self, c):
        self.c, self.t = c, T0

    def feed(self, seconds, field):
        """field(s) recibe los segundos desde el inicio de este tramo."""
        start, end = self.t, self.t + seconds
        while self.t < end - 1e-9:
            r = self.c.post("/data", json=batch(self.t, 10, lambda t: field(t - start)))
            assert r.status_code == 200
            self.t += 0.1


def test_agent_builds_detector_and_connects_actions():
    c = fresh_server()
    clk = Clock(c)
    clk.feed(3, lambda t: 0)                                     # calibracion en reposo
    for _ in range(3):                                           # pasos 1-3: app o panel
        c.post("/record/start", json={"label": "ceja"})
        clk.feed(1.2, lambda t: 25 if 0.3 <= t < 0.8 else 0)
        c.post("/record/stop")
        clk.feed(1.5, lambda t: 0)
    assert server.examples["ceja"] and len(server.examples["ceja"]) == 3

    fake = FakeClient([
        ([block_text("Reviso que hay."), block_tool(1, "ver_estado", {}),
          block_tool(2, "crear_detector", {"tipo": "evento", "etiqueta": "ceja"})], "tool_use"),
        ([block_tool(3, "crear_accion", {"nombre": "decir_tengo_sed", "tipo": "decir",
                                         "descripcion": "Pide agua", "texto": "Tengo sed"}),
          block_tool(4, "conectar", {"detector": "ceja", "gesto": "corto", "accion": "decir_tengo_sed"}),
          block_tool(5, "conectar", {"detector": "ceja", "gesto": "largo", "accion": "musica_pausa"}),
          block_tool(6, "crear_accion", {"nombre": "tv_apagar", "tipo": "http", "descripcion": "Apaga la TV",
                                         "url": "http://192.168.1.50/apagar", "metodo": "POST"}),
          block_tool(7, "conectar", {"detector": "no_existe", "gesto": "corto", "accion": "luz_prender"})],
         "tool_use"),
        ([block_text("Listo: gesto corto dice 'Tengo sed' y largo pausa la musica.")], "end_turn"),
    ])
    server.assistant._client = fake
    with c.websocket_connect("/ws") as ws:
        ws.receive_json(), ws.receive_json()                     # estado inicial y reglas
        r = c.post("/agent", json={"text": "con la ceja corto quiero decir tengo sed"}).json()
        assert r["ok"] and "Tengo sed" in r["reply"]
        kinds = set()
        for _ in range(40):
            m = ws.receive_json()
            kinds.add((m["type"], m.get("role")))
            if m["type"] == "agent" and m.get("role") == "assistant" and not m.get("partial"):
                break
        assert {("agent", "user"), ("agent", "tool"), ("rules", None)} <= kinds

    # Lo que el modelo recibio de vuelta de cada herramienta
    results = {b["tool_use_id"]: b for msg in fake.calls[1:] for b in msg[-1]["content"]}
    estado = json.loads(results["tu_1"]["content"])
    assert estado["ejemplos"] == {"ceja": 3} and estado["telefono"] == "enviando datos"
    det = json.loads(results["tu_2"]["content"])
    assert det["detector"] == "ceja"
    assert det["calidad"] == ("buena" if det["parecido_entre_ejemplos"] >= 0.8 else
                              "baja: conviene regrabar los ejemplos")
    assert json.loads(results["tu_6"]["content"])["estado"] == "pendiente de aprobacion en el panel"
    assert results["tu_7"].get("is_error") is True               # error vuelve al modelo, no rompe
    # El historial queda valido: termina en la respuesta final del asistente
    assert server.assistant.messages[-1]["role"] == "assistant"

    rules = c.get("/rules").json()
    assert [(x["gesto"], x["accion"]) for x in rules["reglas"]] == [("corto", "decir_tengo_sed"),
                                                                    ("largo", "musica_pausa")]
    assert rules["acciones"]["tv_apagar"]["aprobada"] is False
    assert c.post("/actions/approve", json={"name": "tv_apagar"}).json()["ok"]
    assert c.get("/rules").json()["acciones"]["tv_apagar"]["aprobada"] is True

    # Un gesto corto real ejecuta la regla (la voz no suena en pruebas, pero queda en el log)
    clk.feed(0.6, lambda t: 25 if t < 0.4 else 0)
    clk.feed(1.5, lambda t: 0)
    deadline = time.time() + 3
    while time.time() < deadline and not server.engine.log:
        time.sleep(0.05)
    assert [x["accion"] for x in server.engine.log] == ["decir_tengo_sed"]

    # Quitar el detector borra sus reglas
    c.post("/detectors/remove", json={"name": "ceja"})
    assert c.get("/rules").json()["reglas"] == []


def test_probe_counts_gestures_while_phone_sends():
    c = fresh_server()
    clk = Clock(c)
    clk.feed(3, lambda t: 0)
    for _ in range(3):
        c.post("/record/start", json={"label": "dedo"})
        clk.feed(1.2, lambda t: 25 if 0.3 <= t < 0.8 else 0)
        c.post("/record/stop")
        clk.feed(1.0, lambda t: 0)
    c.post("/train", json={"type": "event", "label": "dedo", "action": "none"})

    async def scenario():
        ctx = server.assistant.ctx
        sent = []
        ag = Agent(Context(engine=ctx.engine, status=ctx.status, train=ctx.train,
                           remove_detector=ctx.remove_detector,
                           broadcast=lambda m: _collect(sent, m), say=None), client=object())

        async def gestures():
            await asyncio.sleep(0.2)
            for _ in range(2):                                   # dos gestos cortos
                await _feed_async(clk, 0.5, lambda t: 25 if t < 0.4 else 0)
                await _feed_async(clk, 1.2, lambda t: 0)

        server.state["last_rx"] = time.time()
        g = asyncio.create_task(gestures())
        out = await ag.run_tool("probar_detector", {"nombre": "dedo", "segundos": 5,
                                                    "instruccion": "Haz el gesto 2 veces"})
        await g
        return out, sent

    out, sent = asyncio.run(scenario())
    assert out["gestos_detectados"].get("corto") == 2, out
    assert sent[0] == {"type": "probe", "text": "Haz el gesto 2 veces", "seconds": 5}


async def _collect(lst, m):
    lst.append(m)


async def _feed_async(clk, seconds, field):
    """Alimenta datos sin pasar por HTTP (misma logica del /data) dentro del loop actual."""
    start, end = clk.t, clk.t + seconds
    while clk.t < end - 1e-9:
        for s in batch(clk.t, 10, lambda t: field(t - start))["payload"]:
            v = s["values"]
            for e in server.bank.step(s["time"] / 1e9, (v["x"], v["y"], v["z"])):
                server.engine.handle(e)
        clk.t += 0.1
        server.state["last_rx"] = time.time()
        await asyncio.sleep(0.02)


def test_left_right_light_scenario(monkeypatch):
    """'De izquierda a derecha apaga la luz y de derecha a izquierda la prende'.

    Un telefono simulado manda barridos del iman (campo de dipolo) en tiempo real
    mientras el agente graba 3 intentos de cada sentido, crea el detector de
    trayectoria y conecta las reglas. Luego barridos nuevos manejan la luz.
    """
    import httpx
    import numpy as np
    import agent as agent_mod
    from test_trajectory import dipole

    monkeypatch.setattr(agent_mod, "COUNTDOWN_S", 0.4)     # corta, para que la prueba dure poco
    fresh_server()
    rng = np.random.default_rng(3)
    earth = np.array([20.0, -5.0, -40.0])

    def sweep(direction):
        secs, h, y = rng.uniform(0.5, 1.0), rng.uniform(0.035, 0.05), rng.uniform(-0.008, 0.008)
        m = 0.02 * (np.array([0, 0, 1.0]) + rng.normal(0, 0.15, 3))
        return [dipole(np.array([direction * (-0.09 + 0.18 * s), y, h]), m)
                for s in np.linspace(0, 1, int(secs * 50))]

    async def scenario():
        transport = httpx.ASGITransport(app=server.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            clock = {"t": T0, "queue": [], "stop": False, "seen_rec": None}

            async def phone():
                """50 Hz en paquetes de 0,1 s; durante cada grabacion hace un barrido."""
                while not clock["stop"]:
                    lab = server.rec["label"]
                    if lab and lab != clock["seen_rec"] and not clock["queue"]:
                        clock["queue"] = [np.zeros(3)] * 15 + sweep(+1 if lab == "izq_der" else -1)
                    clock["seen_rec"] = lab or None
                    payload = []
                    for i in range(5):
                        extra = clock["queue"].pop(0) if clock["queue"] else np.zeros(3)
                        v = earth + extra + rng.normal(0, 0.17, 3)
                        payload.append({"name": "magnetometeruncalibrated",
                                        "time": int((clock["t"] + i / 50) * 1e9),
                                        "values": {"x": v[0], "y": v[1], "z": v[2]}})
                    clock["t"] += 0.1
                    await http.post("/data", json={"payload": payload})
                    await asyncio.sleep(0.1)

            async def live_sweep(direction):
                clock["queue"] = sweep(direction) + [np.zeros(3)] * 25
                while clock["queue"]:
                    await asyncio.sleep(0.1)
                await asyncio.sleep(0.4)

            ph = asyncio.create_task(phone())
            await asyncio.sleep(3)                                    # calibracion en reposo
            server.assistant._client = FakeClient([
                ([block_tool(1, "ver_estado", {})], "tool_use"),
                ([block_tool(2, "grabar_ejemplos", {"etiqueta": "izq_der", "segundos": 2,
                                                    "instruccion": "Mueve el iman IZQUIERDA ➜ DERECHA"})],
                 "tool_use"),
                ([block_tool(3, "grabar_ejemplos", {"etiqueta": "der_izq", "segundos": 2,
                                                    "instruccion": "Mueve el iman DERECHA ➜ IZQUIERDA"})],
                 "tool_use"),
                ([block_tool(4, "crear_detector", {"tipo": "trayectoria", "nombre": "mano",
                                                   "etiquetas": ["izq_der", "der_izq"]})], "tool_use"),
                ([block_tool(5, "conectar", {"detector": "mano", "gesto": "gesto:izq_der", "accion": "luz_apagar"}),
                  block_tool(6, "conectar", {"detector": "mano", "gesto": "gesto:der_izq", "accion": "luz_prender"})],
                 "tool_use"),
                ([block_text("Listo: izquierda a derecha apaga, derecha a izquierda prende.")], "end_turn"),
            ])
            reply = await server.assistant.chat("si muevo el iman de izquierda a derecha se apaga la "
                                                "luz y de derecha a izquierda se prende")
            fake = server.assistant._client
            lamp = []
            for d in (-1, +1, -1, +1):
                await live_sweep(d)
                lamp.append(server.det.lamp)
            clock["stop"] = True
            await ph
            return reply, fake, lamp

    reply, fake, lamp = asyncio.run(scenario())
    assert "Listo" in reply
    results = {b["tool_use_id"]: json.loads(b["content"]) for msg in fake.calls[1:]
               for b in msg[-1]["content"]}
    for tu in ("tu_2", "tu_3"):
        assert [a["se_vio"] for a in results[tu]["intentos"]] == [True, True, True], results[tu]
    q = results["tu_4"]
    assert q["acierto"] == 1.0 and q["calidad"] == "buena", q
    assert lamp == [True, False, True, False]           # prende, apaga, prende, apaga


def test_agent_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    c = fresh_server()
    server.assistant._client = None
    s = c.get("/agent/status").json()
    assert s["available"] is False and "ANTHROPIC_API_KEY" in s["reason"]
    r = c.post("/agent", json={"text": "hola"}).json()
    assert "no esta disponible" in r["reply"]
    assert server.assistant.messages == []                       # nada a medias en el historial


# --- modo plan: contrato con la app Android (android/SERVER_API.md) ----------

APP_CONTEXT = {"devices": [{"id": "luz", "name": "Luz"}, {"id": "ventilador", "name": "Ventilador"}],
               "detectors": [], "examples": {}, "bindings": {}}


def test_app_plan_contract():
    c = fresh_server()
    plan = {"reply": "Graba 5 veces el giro a la derecha y toca Hacer en cada paso.",
            "steps": [
                {"type": "record", "label": "derecha", "count": 5, "detector_type": "event",
                 "name": None, "trigger": None, "labels": None, "band": None, "pause_s": None,
                 "detector": None, "device": None},
                {"type": "train", "label": "derecha", "count": None, "detector_type": "event",
                 "name": "derecha", "trigger": "any", "labels": None, "band": None, "pause_s": None,
                 "detector": None, "device": None},
                {"type": "bind", "label": None, "count": None, "detector_type": None, "name": None,
                 "trigger": None, "labels": None, "band": None, "pause_s": None,
                 "detector": "derecha", "device": "luz"},
                {"type": "bind", "label": None, "count": None, "detector_type": None, "name": None,
                 "trigger": None, "labels": None, "band": None, "pause_s": None,
                 "detector": "derecha", "device": "tele_inventada"},       # no existe -> none
                {"type": "train", "label": None, "count": None, "detector_type": "event",
                 "name": "x", "trigger": "any", "labels": None, "band": None, "pause_s": None,
                 "detector": None, "device": None},                         # sin label -> fuera
            ]}
    fake = FakeClient([([block_text(json.dumps(plan))], "end_turn")])
    server.assistant._client = fake
    r = c.post("/agent", json={"text": "Girando a la derecha, prender y apagar la luz",
                               "context": APP_CONTEXT})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"reply", "steps"}
    assert body["steps"] == [
        {"type": "record", "label": "derecha", "count": 5, "detector_type": "event"},
        {"type": "train", "label": "derecha", "detector_type": "event", "name": "derecha", "trigger": "any"},
        {"type": "bind", "detector": "derecha", "device": "luz"},
        {"type": "bind", "detector": "derecha", "device": "none"},
    ]
    sent = json.loads(fake.calls[0][0]["content"])                   # el contexto llega al modelo
    assert sent["context"]["devices"][0]["id"] == "luz"
    assert server.assistant.messages == []                           # no ensucia el chat del panel
    assert server.engine.rules == []                                 # el servidor no ejecuta nada


def test_app_plan_answers_before_app_timeout(monkeypatch):
    import agent as agent_mod
    monkeypatch.setattr(agent_mod, "PLAN_TIMEOUT_S", 0.3)
    c = fresh_server()

    class Slow(FakeClient):
        async def _create(self, **kw):
            await asyncio.sleep(5)

    server.assistant._client = Slow([])
    t = time.time()
    r = c.post("/agent", json={"text": "hola", "context": APP_CONTEXT})
    assert time.time() - t < 2
    assert r.status_code == 503 and "tardo demasiado" in r.json()["error"]


def test_app_plan_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    c = fresh_server()
    server.assistant._client = None
    r = c.post("/agent", json={"text": "hola", "context": APP_CONTEXT})
    assert r.status_code == 503 and "ANTHROPIC_API_KEY" in r.json()["error"]
