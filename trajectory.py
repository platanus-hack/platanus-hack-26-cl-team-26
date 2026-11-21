"""Detector de trayectoria: reconoce movimientos por su forma en el tiempo.

Sirve cuando importa el ORDEN del movimiento, no solo hacia donde empuja el
iman. Ejemplo: pasar el iman de izquierda a derecha frente al telefono y de
derecha a izquierda recorre los mismos campos, pero al reves; el detector de
eventos los ve iguales y este los distingue.

Como funciona:
  1. Recorta el tramo donde el cambio |B - reposo| supera el umbral.
  2. Lo remuestrea a 32 puntos (asi no importa la velocidad) y lo escala para
     que el maximo valga 1 (asi importa poco la distancia exacta).
  3. Lo compara con los ejemplos grabados usando DTW (alineamiento temporal
     elastico) y elige el mas parecido. Lo descarta si no se parece a ninguno,
     o si con 2+ movimientos queda a medio camino: un movimiento real se parece
     varias veces mas al suyo que al otro (en simulacion >= 3,2x; uno ajeno ~1x).

Solo usa numpy.
"""

from __future__ import annotations

from collections import deque

import numpy as np


def _resample(seg: np.ndarray, n: int) -> np.ndarray:
    x = np.linspace(0, len(seg) - 1, n)
    idx = np.arange(len(seg))
    return np.stack([np.interp(x, idx, seg[:, k]) for k in range(3)], axis=1)


def _shape(seg: np.ndarray, n: int) -> np.ndarray:
    s = _resample(np.asarray(seg, float), n)
    peak = float(np.linalg.norm(s, axis=1).max())
    return s / peak if peak > 1e-9 else s


def _dtw(a: np.ndarray, b: np.ndarray, band: int) -> float:
    """Distancia DTW media por punto, con banda de Sakoe-Chiba."""
    n = len(a)
    cost = np.linalg.norm(a[:, None, :] - b[None, :, :], axis=2)
    acc = np.full((n + 1, n + 1), np.inf)
    acc[0, 0] = 0.0
    for i in range(1, n + 1):
        lo, hi = max(1, i - band), min(n, i + band)
        for j in range(lo, hi + 1):
            acc[i, j] = cost[i - 1, j - 1] + min(acc[i - 1, j], acc[i, j - 1], acc[i - 1, j - 1])
    return float(acc[n, n] / (2 * n))


def segment(delta: np.ndarray, thr: float, pad: int = 3) -> np.ndarray | None:
    """Tramo de un ejemplo donde hubo movimiento (|delta| > thr). None si no hubo."""
    delta = np.asarray(delta, float)
    if len(delta) == 0:
        return None
    above = np.nonzero(np.linalg.norm(delta, axis=1) > thr)[0]
    if len(above) < 3:
        return None
    a, b = max(0, above[0] - pad), min(len(delta), above[-1] + pad + 1)
    return delta[a:b]


class TrajectoryDetector:
    kind = "trajectory"
    uses_delta = True            # detectors.Bank le pasa el cambio respecto al reposo

    def __init__(self, name="movimiento", n_points=32, k=6.0, floor=1.0, min_on=0.08,
                 min_off=0.15, max_len=4.0, preroll=0.25, reject=4.0, min_ratio=1.8):
        self.name = name
        self.n = n_points
        self.band = max(2, n_points // 4)
        self.k, self.floor = k, floor
        self.min_on, self.min_off, self.max_len = min_on, min_off, max_len
        self.preroll = preroll
        self.reject = reject
        self.min_ratio = min_ratio
        self.templates: dict[str, list[np.ndarray]] = {}
        self.max_dist = np.inf
        self.reset()

    def reset(self):
        self.active = False
        self.above_since = None
        self.below_since = None
        self.started = None
        self.buf: list[np.ndarray] = []
        self.recent: deque[tuple[float, np.ndarray]] = deque()
        self.count = 0
        self.last = None
        self.dist = None
        self.signal = 0.0

    @property
    def labels(self) -> list[str]:
        return list(self.templates)

    def threshold(self, noise: float) -> float:
        return max(self.k * noise, self.floor)

    # --- entrenamiento ----------------------------------------------------
    def fit(self, examples: dict[str, list[np.ndarray]], noise: float):
        """examples: {"izq_der": [delta(n,3), ...], "der_izq": [...]} con el cambio
        respecto al reposo de cada ejemplo grabado. Devuelve self."""
        thr = self.threshold(noise)
        templates: dict[str, list[np.ndarray]] = {}
        empty = []
        for lab, exs in examples.items():
            shapes = []
            for i, e in enumerate(exs):
                seg = segment(e, thr)
                if seg is None:
                    empty.append(f"{lab} #{i + 1}")
                else:
                    shapes.append(_shape(seg, self.n))
            if shapes:
                templates[lab] = shapes
        if empty:
            raise ValueError("no se vio movimiento en: " + ", ".join(empty) +
                             f" (el cambio no supero {thr:.1f} uT; acerca el iman o regraba)")
        if not templates or sum(len(v) for v in templates.values()) < 2:
            raise ValueError("se necesitan al menos 2 ejemplos")
        self.templates = templates
        # Distancia tipica dentro de cada movimiento -> limite para descartar
        intra = [self._nearest(s, lab, skip=(lab, i))[1]
                 for lab, shapes in templates.items() for i, s in enumerate(shapes)
                 if len(shapes) > 1]
        # Piso chico: con ejemplos muy parecidos no conviene rechazar repeticiones normales
        scale = float(np.median(intra)) if intra else 0.06
        self.max_dist = self.reject * max(scale, 0.03)
        self.reset()
        return self

    def _nearest(self, shape: np.ndarray, only: str | None = None,
                 skip: tuple[str, int] | None = None) -> tuple[str | None, float]:
        best, best_d = None, np.inf
        for lab, shapes in self.templates.items():
            if only is not None and lab != only:
                continue
            for i, t in enumerate(shapes):
                if skip == (lab, i):
                    continue
                d = _dtw(shape, t, self.band)
                if d < best_d:
                    best, best_d = lab, d
        return best, best_d

    def quality(self) -> dict:
        """Calidad con los ejemplos: acierto dejando uno fuera y separacion
        (distancia al otro movimiento / distancia dentro del mismo; > 2 es bueno)."""
        hits, total, intra, inter = 0, 0, [], []
        for lab, shapes in self.templates.items():
            for i, s in enumerate(shapes):
                pred, _ = self._nearest(s, skip=(lab, i))
                total += 1
                hits += int(pred == lab)
                if len(shapes) > 1:
                    intra.append(self._nearest(s, lab, skip=(lab, i))[1])
                others = [self._nearest(s, o)[1] for o in self.templates if o != lab]
                if others:
                    inter.append(min(others))
        q = {"acierto_dejando_uno_fuera": round(hits / total, 2) if total else None,
             "ejemplos": {lab: len(v) for lab, v in self.templates.items()}}
        if intra and inter:
            q["separacion"] = round(float(np.median(inter) / max(np.median(intra), 1e-6)), 2)
        return q

    def classify(self, seg: np.ndarray) -> tuple[str | None, float]:
        shape = _shape(seg, self.n)
        lab, d = self._nearest(shape)
        if lab is None or d > self.max_dist:
            return None, d
        others = [self._nearest(shape, o)[1] for o in self.templates if o != lab]
        if others and min(others) < self.min_ratio * max(d, 1e-6):
            return None, d                # a medio camino entre dos movimientos
        return lab, d

    # --- en vivo ------------------------------------------------------------
    def step(self, t: float, delta: np.ndarray, noise: float) -> list[dict]:
        if not self.templates:
            return []
        delta = np.asarray(delta, float)
        mag = float(np.linalg.norm(delta))
        self.signal = mag
        thr = self.threshold(noise)
        ev: list[dict] = []
        if not self.active:
            self.recent.append((t, delta))
            while self.recent and t - self.recent[0][0] > self.preroll:
                self.recent.popleft()
            if mag > thr:
                if self.above_since is None:
                    self.above_since = t
                if t - self.above_since >= self.min_on:
                    self.active, self.started, self.below_since = True, self.above_since, None
                    self.buf = [d for _, d in self.recent]
                    ev.append({"kind": "start", "t": t})
            else:
                self.above_since = None
            return ev
        self.buf.append(delta)
        if mag < thr / 2:
            if self.below_since is None:
                self.below_since = t
            done = t - self.below_since >= self.min_off
        else:
            self.below_since = None
            done = False
        if done or t - self.started > self.max_len:
            self.active, self.above_since = False, None
            seg = segment(np.array(self.buf), thr) if len(self.buf) >= 3 else None
            self.buf, self.recent = [], deque()
            if seg is None:
                return ev
            lab, d = self.classify(seg)
            self.dist = round(d, 3)
            if lab is None:
                ev.append({"kind": "trajectory", "t": t, "label": None, "dist": self.dist})
            else:
                self.count += 1
                self.last = lab
                ev.append({"kind": "trajectory", "t": t, "label": lab, "dist": self.dist})
        return ev

    def status(self, noise: float) -> dict:
        return {"name": self.name, "type": self.kind, "active": self.active,
                "labels": self.labels, "count": self.count, "last": self.last,
                "signal": round(self.signal, 3), "threshold": round(self.threshold(noise), 3),
                "dist": self.dist}


class PatternDetector(TrajectoryDetector):
    """Un movimiento aprendido por su forma, comparado contra TODOS los movimientos grabados.

    Se presenta como un detector de evento (kind "event"), asi la app Android y el
    panel lo usan igual que los demas: cuando reconoce su movimiento entrega
    "start", "short" y "end". Si el movimiento se parece mas a otro de los grabados
    (o no se parece a ninguno), no entrega nada.
    """

    kind = "event"
    model = "patron"

    def __init__(self, name: str, target: str, **kw):
        super().__init__(name, **kw)
        self.target = target
        self.hits = 0

    def step(self, t: float, delta: np.ndarray, noise: float) -> list[dict]:
        out = []
        for e in super().step(t, delta, noise):
            if e["kind"] == "trajectory" and e.get("label") == self.target:
                self.hits += 1
                out += [{"kind": "start", "t": e["t"]}, {"kind": "short", "t": e["t"]},
                        {"kind": "end", "t": e["t"], "duration": 0.0}]
        return out

    def status(self, noise: float) -> dict:
        return {"name": self.name, "type": "event", "model": self.model, "active": self.active,
                "labels": [self.target], "rivals": [lab for lab in self.labels if lab != self.target],
                "count": self.hits, "last": self.target if self.hits else None,
                "signal": round(self.signal, 3), "threshold": round(self.threshold(noise), 3)}
