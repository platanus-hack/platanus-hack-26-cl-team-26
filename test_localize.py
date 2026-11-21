"""Posicion 3D del iman (localize.py) con un iman simulado (dipolo ideal).

Validan el calculo; la precision real depende de que el iman no se incline,
de la distancia (no menos de ~1,5 cm) y de que no haya metal cerca.
"""
import numpy as np
import pytest

import server
from localize import Tracker, field
from test_learning import FS, Phone

EARTH = np.array([20.0, -5.0, -40.0])
M_TRUE = 0.236 * np.array([0.1, 0.0, 1.0]) / np.linalg.norm([0.1, 0.0, 1.0])   # 10x3 mm, algo inclinado
rng = np.random.default_rng(11)


def calibrated(noise=0.05):
    t = Tracker()
    for _ in range(20):
        t.push(EARTH + rng.normal(0, noise, 3))
    t.set_base()
    for _ in range(20):
        t.push(EARTH + field(np.array([0, 0, 0.03]), M_TRUE) + rng.normal(0, noise, 3))
    return t, t.calibrate(3.0)


def track(t, path, noise=0.05):
    out = []
    for p in path:
        t.push(EARTH + field(p, M_TRUE) + rng.normal(0, noise, 3))
        s = t.update(0.1)
        if s["estado"] == "rastreando":
            out.append(np.linalg.norm(np.array([s["x"], s["y"], s["z"]]) / 100 - p) * 1000)
    return out


def test_calibration_recovers_the_magnet():
    _, cal = calibrated()
    assert cal["momento_Am2"] == pytest.approx(0.236, abs=0.002)
    assert cal["inclinacion_grados"] == pytest.approx(5.7, abs=0.3)


def test_follows_circle_and_height():
    t, _ = calibrated()
    u = np.linspace(0, 1, 300)
    circle = [np.array([0.02 * np.cos(6.28 * a), 0.02 * np.sin(6.28 * a), 0.04]) for a in u]
    lift = [np.array([0.005, -0.005, 0.025 + 0.05 * a]) for a in u]
    for path in (circle, lift):
        errs = track(t, path)
        assert len(errs) == len(path)
        assert max(errs) < 1.0                                   # mm (modelo ideal)


def test_mirror_side_and_far_magnet():
    t, _ = calibrated()
    errs = track(t, [np.array([0.01, 0.01, 0.035])] * 5)
    assert max(errs) < 1.0                                       # elige el lado de la pantalla
    t.push(EARTH + rng.normal(0, 0.05, 3))
    assert t.update(0.1)["estado"] == "lejos"


def test_calibration_errors_are_explained():
    t = Tracker()
    with pytest.raises(ValueError, match="faltan datos"):
        t.set_base()
    for _ in range(20):
        t.push(EARTH)
    with pytest.raises(ValueError, match="primero mide sin iman"):
        t.calibrate(3)
    t.set_base()
    for _ in range(20):
        t.push(EARTH + rng.normal(0, 0.05, 3))
    with pytest.raises(ValueError, match="casi no cambia"):
        t.calibrate(3)
    for i in range(20):                                          # se esta moviendo
        t.push(EARTH + field(np.array([0, 0, 0.03 + 0.002 * i]), M_TRUE))
    with pytest.raises(ValueError, match="moviendo"):
        t.calibrate(3)


def test_through_the_server():
    ph = Phone()
    server.tracker.reset()
    ph.rest(2)
    assert ph.c.post("/tracker/base").json()["ok"]
    at = lambda p, secs=0.6: ph.send([field(np.array(p), M_TRUE)] * int(secs * FS))
    at([0, 0, 0.03])
    cal = ph.c.post("/tracker/calibrate", json={"dist_cm": 3}).json()
    assert cal["ok"] and cal["momento_Am2"] == pytest.approx(0.236, rel=0.05), cal
    for p in ([0.01, -0.015, 0.04], [-0.02, 0.01, 0.05], [0.0, 0.02, 0.035]):
        at(p)
        s = ph.c.get("/tracker").json()
        assert s["estado"] == "rastreando", s
        est = np.array([s["x"], s["y"], s["z"]]) / 100
        assert np.linalg.norm(est - np.array(p)) < 0.002, (s, p)  # < 2 mm con el ruido del telefono
        assert s["confianza"] > 0.9
    with ph.c.websocket_connect("/ws") as ws:
        ws.receive_json(), ws.receive_json()
        ph.rest(0.2)
        m = ws.receive_json()
        assert m["type"] == "data" and "tracker" in m
