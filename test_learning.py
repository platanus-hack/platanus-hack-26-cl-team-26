"""Aprendizaje automatico de movimientos a traves del servidor (como lo usa la app).

/record/start -> datos -> /record/stop varias veces, y luego /train con
type "event" (lo unico que manda la app). El servidor analiza los ejemplos y
elige el modelo. Datos generados con un iman simulado (campo de dipolo): validan
la logica; el acierto real se mide con el iman.
"""
import json
import tempfile
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

import server
from test_trajectory import dipole

FS = 50
EARTH = np.array([20.0, -5.0, -40.0])
rng = np.random.default_rng(7)


class Phone:
    """Telefono simulado: manda lecturas a /data en paquetes de 0,1 s."""

    def __init__(self):
        server.DATA_DIR = Path(tempfile.mkdtemp())
        server.det.reset()
        server.bank.detectors.clear()
        server.bank.pipeline.reset()
        server.examples.clear()
        server.state.update(csv_writer=None, first_saved=False, last_rx=None)
        server.engine.path = server.DATA_DIR / "acciones.json"
        server.engine.load()
        self.c = TestClient(server.app)
        self.t = 1_700_000_000.0

    def send(self, field_list):
        """field_list: lista de vectores extra (uT), uno por muestra a 50 Hz."""
        for i in range(0, len(field_list), 5):
            chunk = field_list[i:i + 5]
            payload = []
            for k, extra in enumerate(chunk):
                v = EARTH + extra + rng.normal(0, 0.15, 3)
                payload.append({"name": "magnetometeruncalibrated", "time": int((self.t + k / FS) * 1e9),
                                "values": {"x": v[0], "y": v[1], "z": v[2]}})
            self.t += len(chunk) / FS
            assert self.c.post("/data", json={"payload": payload}).status_code == 200

    def rest(self, secs):
        self.send([np.zeros(3)] * int(secs * FS))

    def record(self, label, movement, pre=0.3, post=0.5):
        self.c.post("/record/start", json={"label": label})
        self.rest(pre)
        self.send(movement)
        self.rest(post)
        self.c.post("/record/stop")
        self.rest(0.8)


def sweep(direction):
    """Iman que pasa frente al sensor: +1 izquierda->derecha, -1 al reves."""
    secs, h, y = rng.uniform(0.5, 1.0), rng.uniform(0.035, 0.05), rng.uniform(-0.008, 0.008)
    m = 0.02 * (np.array([0, 0, 1.0]) + rng.normal(0, 0.15, 3))
    return [dipole(np.array([direction * (-0.09 + 0.18 * s), y, h]), m)
            for s in np.linspace(0, 1, int(secs * FS))]


def push(direction):
    """Dedo con iman que se corre hacia un lado y vuelve (sin cruzar el sensor)."""
    m = np.array([0, 0, 0.01])
    n = int(rng.uniform(0.5, 0.9) * FS)
    path = np.concatenate([np.linspace(0, 1, n // 2), np.linspace(1, 0, n - n // 2)])
    base = dipole(np.array([0.0, 0.0, 0.035]), m)
    return [dipole(np.array([direction * 0.012 * s, 0.0, 0.035]), m) - base for s in path]


def train(ph, label):
    return ph.c.post("/train", json={"type": "event", "name": label, "label": label,
                                     "action": "none", "trigger": "any"})


def hits(name):
    d = server.bank.detectors[name].det
    return getattr(d, "hits", None) if hasattr(d, "hits") else d.count


def test_sweeps_learn_by_pattern_and_work_like_events():
    ph = Phone()
    ph.rest(3)
    for _ in range(4):
        ph.record("izq_der", sweep(+1))
        ph.record("der_izq", sweep(-1))
    r1, r2 = train(ph, "izq_der").json(), train(ph, "der_izq").json()
    assert r1["ok"] and r2["ok"], (r1, r2)
    assert r1["info"]["model"] == "patron" and r2["info"]["model"] == "patron"
    assert r1["info"]["consistency"] == 1.0                         # lo que muestra la app
    status = ph.c.get("/status").json()["phase2"]["detectors"]
    assert {d["type"] for d in status} == {"event"}                 # la app los acepta
    with ph.c.websocket_connect("/ws") as ws:
        ws.receive_json(), ws.receive_json()
        for direction in (+1, -1, -1, +1, -1):
            ph.rest(0.3)
            ph.send(sweep(direction))
            ph.rest(0.6)
    assert (hits("izq_der"), hits("der_izq")) == (2, 3)


def test_pushes_left_right_learn_by_direction():
    ph = Phone()
    ph.rest(3)
    for _ in range(4):
        ph.record("izquierda", push(-1))
        ph.record("derecha", push(+1))
    r = train(ph, "derecha").json()
    assert r["ok"] and r["info"]["model"] == "direccion", r
    an = ph.c.get("/examples/analysis").json()
    assert an["pares"][0]["coseno_direcciones"] < 0                 # empujan hacia lados opuestos


def test_rejects_examples_without_movement():
    ph = Phone()
    ph.rest(3)
    for _ in range(5):
        ph.record("girar_der", [np.zeros(3)] * 40)                 # el iman no llego al sensor
    r = train(ph, "girar_der")
    assert r.status_code == 400
    err = r.json()["error"]
    assert "0 de 5" in err and "2-3 cm" in err
    assert "girar_der" not in server.bank.detectors
    an = ph.c.get("/examples/analysis").json()["etiquetas"]["girar_der"]
    assert an["vistos"] == 0 and an["modelo_sugerido"] is None


def test_drops_the_bad_example_and_warns():
    ph = Phone()
    ph.rest(3)
    for i in range(5):
        ph.record("toque", [np.zeros(3)] * 40 if i == 2 else push(+1))
    r = train(ph, "toque").json()
    assert r["ok"], r
    assert r["info"]["vistos"] == 4
    assert any("1 de 5" in a for a in r["info"]["avisos"])


def test_plan_receives_the_analysis():
    import test_agent as ta
    ph = Phone()
    ph.rest(3)
    for _ in range(3):
        ph.record("girar_der", [np.zeros(3)] * 40)
    fake = ta.FakeClient([([ta.block_text(json.dumps({"reply": "ok", "steps": []}))], "end_turn")])
    server.assistant._client = fake
    r = ph.c.post("/agent", json={"text": "girar a la derecha prende la luz", "context": ta.APP_CONTEXT})
    assert r.status_code == 200
    sent = json.loads(fake.calls[0][0]["content"])
    g = sent["analisis"]["etiquetas"]["girar_der"]
    assert g["vistos"] == 0 and "acerca el iman" in g["problema"].lower()


# --- "girar" contra acercar o mover recto: contraejemplos "otros" -------------

def twist(sign, deg=None):
    """Girar la muñeca: el iman se inclina y vuelve, en el mismo lugar."""
    deg = deg if deg is not None else rng.uniform(45, 70)
    pos = np.array([0.008, 0.0, 0.035]) + rng.normal(0, 0.001, 3)
    n = int(rng.uniform(0.6, 0.9) * FS)
    th = np.radians(sign * deg) * np.concatenate([np.linspace(0, 1, n // 2), np.linspace(1, 0, n - n // 2)])
    m0 = 0.01
    base = dipole(pos, np.array([0, 0, m0]))
    return [dipole(pos, m0 * np.array([np.sin(a), 0.0, np.cos(a)])) - base for a in th]


def approach():
    """Acercar el iman al celular y alejarlo, sin girarlo."""
    n = int(rng.uniform(0.6, 0.9) * FS)
    z = 0.035 + 0.02 * np.concatenate([np.linspace(1, 0, n // 2), np.linspace(0, 1, n - n // 2)])
    base = dipole(np.array([0.008, 0, 0.035]), np.array([0, 0, 0.01]))
    return [dipole(np.array([0.008, 0, zz]), np.array([0, 0, 0.01])) - base for zz in z]


def straight(sign):
    """Mover el iman recto hacia un lado y volver, sin girarlo."""
    n = int(rng.uniform(0.6, 0.9) * FS)
    x = sign * 0.012 * np.concatenate([np.linspace(0, 1, n // 2), np.linspace(1, 0, n - n // 2)])
    base = dipole(np.array([0.008, 0, 0.035]), np.array([0, 0, 0.01]))
    return [dipole(np.array([0.008 + xx, 0, 0.035]), np.array([0, 0, 0.01])) - base for xx in x]


def live_fires(ph, name, moves):
    before = hits(name)
    out = []
    for mv in moves:
        ph.rest(0.4)
        ph.send(mv)
        ph.rest(2.0)
        now = hits(name)
        out.append(now - before)
        before = now
    return out


def test_otros_stop_false_activations_of_a_twist():
    distractors = [approach, lambda: straight(-1), lambda: straight(+1), lambda: twist(-1)]
    # 1) Solo el gesto: se activa con movimientos que no son el gesto (el problema reportado)
    ph = Phone()
    ph.rest(3)
    for _ in range(5):
        ph.record("girar_izq", twist(+1))
    r = train(ph, "girar_izq").json()
    assert r["ok"], r
    assert any("otros" in a for a in r["info"]["avisos"])           # el analisis lo advierte
    alone = live_fires(ph, "girar_izq", [d() for d in distractors for _ in range(2)])
    assert sum(alone) >= 2, alone

    # 2) Con contraejemplos "otros": ya no se activa con ellos y sigue reconociendo el giro
    ph = Phone()
    ph.rest(3)
    for _ in range(5):
        ph.record("girar_izq", twist(+1))
    for mv in (approach(), straight(-1), straight(+1), twist(-1), approach()):
        ph.record("otros", mv)
    assert train(ph, "otros").status_code == 400                  # "otros" no es un gesto
    r = train(ph, "girar_izq").json()
    assert r["ok"], r                       # el modelo lo elige el servidor; importa el resultado
    false_fires = live_fires(ph, "girar_izq", [d() for d in distractors for _ in range(2)])
    true_fires = live_fires(ph, "girar_izq", [twist(+1) for _ in range(5)])
    assert sum(false_fires) <= 1, false_fires
    assert sum(true_fires) >= 3, true_fires          # prefiere no activarse si duda
