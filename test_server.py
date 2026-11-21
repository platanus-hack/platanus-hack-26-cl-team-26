"""Pruebas de la fase 1 con datos de prueba (solo para validar el codigo, no para la demo)."""
import tempfile
from pathlib import Path
import random
from fastapi.testclient import TestClient
import server

RATE = 100  # Hz


def batch(t0, n, field, name="magnetometeruncalibrated", noise=0.2):
    """n lecturas desde t0 (s) con campo extra `field(t)` en uT sobre la Tierra."""
    out = []
    for i in range(n):
        t = t0 + i / RATE
        extra = field(t)
        out.append({"name": name, "time": int(t * 1e9),
                    "values": {"x": 20 + extra + random.gauss(0, noise),
                               "y": -5 + random.gauss(0, noise),
                               "z": -40 + random.gauss(0, noise)}})
    return {"messageId": 1, "sessionId": "test", "deviceId": "x", "payload": out}


def run(client, field, seconds, start=0.0, extra_names=()):
    step = 0.2
    t0 = 1_700_000_000.0
    t = t0 + start
    while t < t0 + seconds - 1e-9:
        b = batch(t, int(step * RATE), field)
        for nm in extra_names:  # lecturas calibradas, deben ignorarse
            b["payload"] += batch(t, int(step * RATE), lambda _t: 500, name=nm)["payload"]
        r = client.post("/data", json=b)
        assert r.status_code == 200
        t += step


def fresh():
    server.DATA_DIR = Path(tempfile.mkdtemp())   # nunca tocar data/ real
    server.det.reset()
    server.bank.detectors.clear()
    server.bank.pipeline.reset()
    server.state.update(csv_writer=None, first_saved=False)
    return TestClient(server.app)


def test_two_gestures_and_ignored_spike():
    c = fresh()
    def field(t):
        rel = t - 1_700_000_000.0
        if 3 <= rel < 4: return 30         # gesto 1
        if 5 <= rel < 5.05: return 30      # pico de 50 ms
        if 6 <= rel < 7: return 30         # gesto 2
        return 0
    run(c, field, 8, extra_names=("magnetometer",))
    s = c.get("/status").json()
    assert not s["calibrating"]
    assert s["activations"] == 2, s
    assert s["lamp"] is False            # alterno dos veces


def test_hold_mode_and_stuck_magnet():
    c = fresh()
    c.post("/config", json={"mode": "hold"})
    def field(t):
        rel = t - 1_700_000_000.0
        if 3 <= rel < 4: return 30
        if rel >= 5: return 40             # iman se queda en otro lugar
        return 0
    run(c, field, 4.5)
    assert c.get("/status").json()["lamp"] is False
    run(c, field, 14, start=4.6)
    s = c.get("/status").json()
    assert s["activations"] == 2
    assert s["active"] is False and s["lamp"] is False   # no queda pegado


def test_app_event_is_broadcast_to_panel():
    c = fresh()
    with c.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "state"
        assert ws.receive_json()["type"] == "rules"     # reglas gesto -> accion (fase 3)
        r = c.post("/app-event", json={"type": "selected", "text": "Luz: Encendiendo luz",
                                       "time": 1700000000000, "signal": 12.5})
        assert r.status_code == 200
        m = ws.receive_json()
        assert m["type"] == "app_event"
        assert m["event"] == {"type": "selected", "text": "Luz: Encendiendo luz",
                              "time": 1700000000000, "signal": 12.5}
    assert c.post("/app-event", content=b"no es json").status_code == 400
    assert c.post("/app-event", json={"text": "sin tipo"}).status_code == 400


def test_websocket_and_csv():
    c = fresh()
    with c.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "state"
        assert ws.receive_json()["type"] == "rules"     # reglas gesto -> accion (fase 3)
        c.post("/data", json=batch(1_700_000_000.0, 20, lambda t: 0))
        m = ws.receive_json()
        assert m["type"] == "data" and len(m["points"]) == 20
    assert c.get("/").status_code == 200
    assert (server.DATA_DIR / "first_message.json").exists()
    assert open(server.state["csv_path"]).read().count("\n") >= 21
