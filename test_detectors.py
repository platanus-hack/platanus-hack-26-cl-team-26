"""Pruebas de la fase 2 con datos de prueba (solo validan el codigo)."""
import tempfile
from pathlib import Path
import math

import numpy as np
from fastapi.testclient import TestClient

import server
from detectors import (Bank, DirectionModel, EventDetector, RhythmDetector,
                       StateDetector)

FS = 100
EARTH = np.array([20.0, -5.0, -40.0])
rng = np.random.default_rng(0)


def stream(seconds, field, t0=0.0, noise=0.15, rot=None):
    """Lecturas (t, B en el marco del telefono). rot(t) -> angulo de giro en z (rad)."""
    out = []
    for i in range(int(seconds * FS)):
        t = t0 + i / FS
        b = EARTH + field(t)
        if rot is not None:
            a = rot(t)
            c, s = math.cos(a), math.sin(a)
            Rz = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
            b = Rz.T @ b                      # el telefono gira +a: el campo se ve girar -a
        out.append((t, b + rng.normal(0, noise, 3)))
    return out


def run(bank, data, gyro=None):
    ev = []
    for t, v in data:
        if gyro is not None:
            bank.gyro(t, gyro(t))
        ev.extend(bank.step(t, v))
    return ev


U = np.array([0.0, 1.0, 0.0])        # direccion en que empuja el iman
V = np.array([1.0, 0.0, 0.0])        # otra fuente (p. ej. un notebook)


def pulse(t0, t1, vec, amp):
    return lambda t: vec * amp if t0 <= t < t1 else np.zeros(3)


def add(*fs):
    return lambda t: sum((f(t) for f in fs), np.zeros(3))


def test_direction_rejects_other_sources():
    exs = [np.outer(np.linspace(0, 1, 30), U * 8) + rng.normal(0, .1, (30, 3)) for _ in range(3)]
    dm = DirectionModel.fit(exs)
    assert dm.consistency(exs) > 0.95 and abs(dm.u @ U) > 0.99
    field = add(pulse(3, 4, U, 8), pulse(6, 7, V, 8))          # gesto real + perturbacion
    starts = {}
    for name, d in [("dir", dm), ("mag", None)]:
        b = Bank()
        b.add(EventDetector("g", direction=d))
        starts[name] = [e for e in run(b, stream(9, field)) if e["kind"] == "start"]
    assert len(starts["dir"]) == 1 and 3 <= starts["dir"][0]["t"] < 4.5
    assert len(starts["mag"]) == 2        # la fase 1 se confunde con la perturbacion


def test_short_long_double():
    field = add(pulse(3, 3.3, U, 8), pulse(5, 6.5, U, 8),
                pulse(8, 8.3, U, 8), pulse(8.6, 8.9, U, 8))
    b = Bank()
    b.add(EventDetector("g"))
    kinds = [e["kind"] for e in run(b, stream(11, field)) if e["kind"] in ("short", "long", "double")]
    assert kinds == ["short", "long", "double"], kinds


def test_rhythm_rate_and_pause():
    breath = lambda t: U * 3 * math.sin(2 * math.pi * 0.25 * t) if t < 30 else np.zeros(3)
    b = Bank()
    d = RhythmDetector("resp", band=(0.1, 0.7), pause_s=8)
    b.add(d)
    ev = run(b, stream(28, breath))
    assert d.present and abs(d.freq * 60 - 15) < 1.5, d.freq
    ev = run(b, stream(14, breath, t0=28))
    pauses = [e for e in ev if e["kind"] == "pause"]
    assert len(pauses) == 1 and 30 < pauses[0]["t"] < 30 + 8 + 2


def test_state():
    closed, opened = np.zeros(3), V * 15
    smooth = lambda off, n=60: EARTH + off + rng.normal(0, .1, (n, 3))
    d = StateDetector("puerta").fit({"cerrada": [smooth(closed)], "abierta": [smooth(opened)]})
    assert d.separation() > 2
    b = Bank()
    b.add(d, trigger="abierta")
    field = lambda t: opened if 4 <= t < 6 else closed
    ev = [e for e in run(b, stream(8, field)) if e["kind"] == "state"]
    assert [e["state"] for e in ev] == ["cerrada", "abierta", "cerrada"]
    assert [e["action"] for e in ev] == ["off", "on", "off"]


def test_gyro_ignores_slow_turn():
    # El telefono gira 10 grados lento (0.15 rad/s) sin iman: no debe detectar nada
    rate = 0.15
    ang = lambda t: 0.0 if t < 3 else min((t - 3) * rate, math.radians(10))
    w = lambda t: (0, 0, rate if 3 <= t < 3 + math.radians(10) / rate else 0.0)
    data = stream(8, lambda t: np.zeros(3), rot=ang)
    with_g, without = Bank(), Bank()
    with_g.add(EventDetector("g"))
    without.add(EventDetector("g"))
    assert not [e for e in run(with_g, data, gyro=w) if e["kind"] == "start"]
    assert [e for e in run(without, data) if e["kind"] == "start"]   # sin giroscopio se confunde


def test_slow_drift_does_not_trigger():
    # El campo se corre 8 uT en 40 s (deriva, parlante cerca): no es un gesto
    drift = lambda t: V * 8 * min(max(t - 3, 0) / 40, 1)
    field = add(drift, pulse(50, 50.6, U, 8))                         # y luego un gesto real
    b = Bank()
    b.add(EventDetector("g"))
    starts = [e for e in run(b, stream(53, field)) if e["kind"] == "start"]
    assert len(starts) == 1 and 50 <= starts[0]["t"] < 50.6, starts


def test_phase1_drift_does_not_trigger():
    d = server.Detector()
    ons = []
    for t, v in stream(53, add(lambda t: V * 8 * min(max(t - 3, 0) / 40, 1), pulse(50, 50.6, U, 8))):
        if "on" in d.process(t, *v):
            ons.append(t)
    assert len(ons) == 1 and 50 <= ons[0] < 50.6, ons


def test_gyro_pauses_detection_on_fast_move():
    ang = lambda t: 0.0 if t < 3 else min((t - 3) * 2.0, 1.0)       # giro rapido de 57 grados
    w = lambda t: (0, 0, 2.0 if 3 <= t < 3.5 else 0.0)
    field = pulse(6, 7, U, 8)                                       # despues, un gesto real
    b = Bank()
    b.add(EventDetector("g"))
    starts = [e for e in run(b, stream(9, field, rot=ang), gyro=w) if e["kind"] == "start"]
    assert len(starts) == 1 and 6 <= starts[0]["t"] < 6.5


def test_server_record_train_and_gyro():
    server.DATA_DIR = Path(tempfile.mkdtemp())   # nunca tocar data/ real
    server.det.reset()
    server.bank.detectors.clear()
    server.bank.pipeline.reset()
    server.examples.clear()
    server.state.update(csv_writer=None, first_saved=False)
    c = TestClient(server.app)

    def send(t0, secs, field, gyro=0.0):
        payload = []
        for t, v in stream(secs, field, t0=t0):
            ns = int((1_700_000_000 + t) * 1e9)
            payload.append({"name": "magnetometer", "time": ns, "values": dict(zip("xyz", v))})
            payload.append({"name": "gyroscope", "time": ns, "values": {"x": 0, "y": 0, "z": gyro}})
        assert c.post("/data", json={"payload": payload}).status_code == 200

    send(0, 3, lambda t: np.zeros(3))                     # calibra
    for k in range(3):                                    # 3 ejemplos
        t0 = 3 + 2 * k
        send(t0, 0.5, lambda t: np.zeros(3))
        c.post("/record/start", json={"label": "contraccion"})
        send(t0 + 0.5, 0.8, lambda t: U * 6)
        assert c.post("/record/stop").json()["examples"] == k + 1
        send(t0 + 1.3, 0.7, lambda t: np.zeros(3))
    r = c.post("/train", json={"type": "event", "label": "contraccion"}).json()
    assert r["ok"] and r["info"]["consistency"] > 0.9, r
    lamp0 = c.get("/status").json()["lamp"]
    send(10, 1, lambda t: U * 6)                          # gesto -> alterna
    send(11, 1.5, lambda t: np.zeros(3))
    s = c.get("/status").json()
    assert s["lamp"] != lamp0
    assert s["phase2"]["gyro"] is True
    send(12.5, 1, lambda t: U * 6, gyro=1.5)              # telefono moviendose: no cuenta
    assert c.get("/detectors").json()["detectors"][0]["count"] == 1
    assert c.post("/train", json={"type": "rhythm"}).json()["ok"]
    assert len(c.get("/detectors").json()["detectors"]) == 2
