"""Detector de trayectoria con barridos simulados de un iman (campo de dipolo).

Datos generados por el codigo solo para validar la logica; el acierto real
se mide con grabaciones del iman.
"""
import numpy as np

from trajectory import TrajectoryDetector

FS = 50                      # Hz, lo que entrega el telefono de las pruebas
NOISE = 0.17                 # uT, ruido medido en la prueba 2
rng = np.random.default_rng(1)


def dipole(sensor_to_magnet: np.ndarray, m: np.ndarray) -> np.ndarray:
    """Campo (uT) en el sensor de un dipolo m (A m^2) ubicado en sensor_to_magnet (m)."""
    r = -sensor_to_magnet
    d = np.linalg.norm(r)
    rh = r / d
    return 1e-7 * (3 * (m @ rh) * rh - m) / d ** 3 * 1e6


def sweep(direction: int, secs=None, h=None, y=None, m0=0.02, rest=0.6):
    """Iman pasando frente al sensor en x: +1 izquierda->derecha, -1 al reves."""
    secs = secs if secs is not None else rng.uniform(0.5, 1.2)
    h = h if h is not None else rng.uniform(0.035, 0.05)
    y = y if y is not None else rng.uniform(-0.008, 0.008)
    tilt = rng.normal(0, 0.15, 3)
    m = m0 * (np.array([0, 0, 1.0]) + tilt)
    out = [np.zeros(3)] * int(rest * FS)
    for s in np.linspace(0, 1, int(secs * FS)):
        x = direction * (-0.09 + 0.18 * s)
        out.append(dipole(np.array([x, y, h]), m))
    out += [np.zeros(3)] * int(rest * FS)
    return np.array(out) + rng.normal(0, NOISE, (len(out), 3))


def train():
    ex = {"izq_der": [sweep(+1) for _ in range(3)], "der_izq": [sweep(-1) for _ in range(3)]}
    return TrajectoryDetector("mano").fit(ex, noise=NOISE)


def live(det, data):
    ev = []
    for i, v in enumerate(data):
        ev += det.step(i / FS, v, NOISE)
    return [e for e in ev if e["kind"] == "trajectory"]


def test_learns_direction_of_sweep():
    det = train()
    q = det.quality()
    assert q["acierto_dejando_uno_fuera"] == 1.0, q
    assert q["separacion"] > 2, q
    for direction, label in [(+1, "izq_der"), (-1, "der_izq")]:
        for _ in range(8):                           # velocidades y alturas nuevas
            ev = live(det, sweep(direction))
            assert [e["label"] for e in ev] == [label], ev


def test_rejects_other_movements_and_quiet():
    det = train()
    assert live(det, np.zeros((200, 3)) + rng.normal(0, NOISE, (200, 3))) == []   # reposo
    # Acercar y alejar el iman en vertical, sin barrer: no es ninguno de los dos
    approach = [np.zeros(3)] * 30
    for s in np.concatenate([np.linspace(0, 1, 25), np.linspace(1, 0, 25)]):
        approach.append(dipole(np.array([0.0, 0.0, 0.12 - 0.08 * s]), np.array([0, 0, 0.02])))
    approach += [np.zeros(3)] * 30
    ev = live(det, np.array(approach) + rng.normal(0, NOISE, (len(approach), 3)))
    assert all(e["label"] is None for e in ev), ev


def test_reports_examples_without_movement():
    quiet = np.zeros((100, 3)) + rng.normal(0, NOISE, (100, 3))
    try:
        TrajectoryDetector().fit({"izq_der": [sweep(+1), quiet], "der_izq": [sweep(-1)]}, noise=NOISE)
    except ValueError as e:
        assert "izq_der #2" in str(e)
    else:
        raise AssertionError("debio avisar que un ejemplo no tiene movimiento")
