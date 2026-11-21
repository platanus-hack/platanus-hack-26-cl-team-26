"""Detector de trayectoria: reconoce movimientos por su forma en el tiempo.

Sirve cuando importa el ORDEN del movimiento, no solo hacia donde empuja el
iman. Ejemplo: pasar el iman de izquierda a derecha frente al telefono y de
derecha a izquierda recorre los mismos campos, pero al reves; el detector de
eventos los ve iguales y este los distingue.

Como funciona:
  1. Toma una ventana fija desde que el cambio |B - reposo| supera el umbral
     (aprendida de los ejemplos, 0,4 a 1,6 s). Asi decide aunque el iman no
     vuelva a su lugar, y lo mismo al entrenar que en vivo.
  2. Lo remuestrea a 32 puntos (asi no importa la velocidad) y lo escala para
     que el maximo valga 1 (asi importa poco la distancia exacta).
  3. Mide cuanto GIRA el vector del campo y en torno a que eje. Girar el iman
     cambia su orientacion y el campo rota; acercarlo o moverlo recto cambia
     sobre todo el tamano. Asi se distingue "girar" de "mover" aunque la forma
     normalizada se parezca.
  4. Lo compara con los ejemplos grabados (forma con DTW, alineamiento temporal
     elastico, mas la diferencia de giro) y elige el mas parecido. Lo descarta si
     no se parece a ninguno, si lo mas parecido es un contraejemplo ("otros":
     movimientos que NO deben activar) o si queda a medio camino entre dos.

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


ROT_WEIGHT = 0.15     # distancia extra por cada 90 grados de diferencia de giro


def is_negative(label: str) -> bool:
    """Etiqueta de contraejemplos: movimientos que NO deben activar nada ("otros")."""
    lab = str(label).strip().lower()
    return lab in ("otros", "otro", "nada", "ninguno", "no") or lab.startswith(("otros_", "no_"))


def rotation(seg: np.ndarray, thr: float) -> np.ndarray:
    """Giro acumulado del vector del campo (eje x angulo, en radianes)."""
    seg = np.asarray(seg, float)
    m = np.linalg.norm(seg, axis=1)
    ok = m > thr / 2
    if ok.sum() < 2:
        return np.zeros(3)
    u = seg[ok] / m[ok, None]
    cr = np.cross(u[:-1], u[1:])
    s = np.linalg.norm(cr, axis=1)
    ang = np.arcsin(np.clip(s, 0.0, 1.0))
    return (cr / np.maximum(s, 1e-9)[:, None] * ang[:, None]).sum(axis=0)


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


def onset_window(delta: np.ndarray, thr: float, n_after: int, pad: int = 3) -> np.ndarray | None:
    """Desde un poco antes de que el cambio supere el umbral hasta n_after muestras despues.
    Si el ejemplo termina antes, repite la ultima lectura (el iman quedo ahi)."""
    delta = np.asarray(delta, float)
    if len(delta) == 0:
        return None
    above = np.nonzero(np.linalg.norm(delta, axis=1) > thr)[0]
    if len(above) < 3:
        return None
    a = above[0]
    seg = delta[max(0, a - pad):a + n_after]
    missing = (min(pad, a) + n_after) - len(seg)
    if missing > 0:
        seg = np.vstack([seg, np.repeat(seg[-1:], missing, axis=0)])
    return seg


def learn_window(examples: list[np.ndarray], thr: float, rate: float) -> float:
    """Duracion tipica del movimiento completo (de que empieza a que vuelve), mas un
    margen, entre 0,4 y 1,6 s. Si no vuelve (grabacion cortada), cuenta hasta el final."""
    times = []
    for e in examples:
        m = np.linalg.norm(np.asarray(e, float), axis=1)
        above = np.nonzero(m > thr)[0]
        if len(above) >= 3:
            times.append((above[-1] - above[0] + 1) / rate)
    w = float(np.median(times)) + 0.2 if times else 0.8
    return float(min(max(w, 0.4), 1.6))


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
        self.window_s = 0.8            # se aprende en fit()
        # Cada plantilla: (forma normalizada (n,3), giro (3,))
        self.templates: dict[str, list[tuple[np.ndarray, np.ndarray]]] = {}
        self.max_dist = np.inf
        self.reset()

    def reset(self):
        self.active = False
        self.above_since = None
        self.below_since = None
        self.started = None
        self.classified = False
        self.buf: list[np.ndarray] = []
        self.recent: deque[tuple[float, np.ndarray]] = deque()
        self.count = 0
        self.last = None
        self.dist = None
        self.signal = 0.0

    @property
    def labels(self) -> list[str]:
        return list(self.templates)

    def _features(self, seg: np.ndarray, thr: float) -> tuple[np.ndarray, np.ndarray]:
        return _shape(seg, self.n), rotation(seg, thr)

    def _distance(self, a, b) -> float:
        return _dtw(a[0], b[0], self.band) + ROT_WEIGHT * float(np.linalg.norm(a[1] - b[1])) / (np.pi / 2)

    def threshold(self, noise: float) -> float:
        return max(self.k * noise, self.floor)

    # --- entrenamiento ----------------------------------------------------
    def fit(self, examples: dict[str, list[np.ndarray]], noise: float, rate: float = 50.0):
        """examples: {"izq_der": [delta(n,3), ...], "der_izq": [...]} con el cambio
        respecto al reposo de cada ejemplo grabado. Devuelve self."""
        thr = self.threshold(noise)
        rate = rate or 50.0
        gestures = [e for lab, exs in examples.items() if not is_negative(lab) for e in exs]
        self.window_s = learn_window(gestures, thr, rate)
        n_after = max(3, int(round(self.window_s * rate)))
        templates: dict[str, list[tuple[np.ndarray, np.ndarray]]] = {}
        empty = []
        for lab, exs in examples.items():
            shapes = []
            for i, e in enumerate(exs):
                seg = onset_window(e, thr, n_after)
                if seg is None:
                    empty.append(f"{lab} #{i + 1}")
                else:
                    shapes.append(self._features(seg, thr))
            if shapes:
                templates[lab] = shapes
        if empty and not all(is_negative(x.split(" #")[0]) for x in empty):
            raise ValueError("no se vio movimiento en: " + ", ".join(empty) +
                             f" (el cambio no supero {thr:.1f} uT; acerca el iman o regraba)")
        if not [lab for lab in templates if not is_negative(lab)]:
            raise ValueError("se necesita al menos un movimiento que no sea 'otros'")
        if sum(len(v) for v in templates.values()) < 2:
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

    def _nearest(self, feat, only: str | None = None,
                 skip: tuple[str, int] | None = None) -> tuple[str | None, float]:
        best, best_d = None, np.inf
        for lab, shapes in self.templates.items():
            if only is not None and lab != only:
                continue
            for i, t in enumerate(shapes):
                if skip == (lab, i):
                    continue
                d = self._distance(feat, t)
                if d < best_d:
                    best, best_d = lab, d
        return best, best_d

    def quality(self) -> dict:
        """Calidad con los ejemplos: acierto dejando uno fuera y separacion
        (distancia al otro movimiento / distancia dentro del mismo; > 2 es bueno)."""
        hits, total, intra, inter = 0, 0, [], []
        neg_ok, neg_total = 0, 0
        for lab, shapes in self.templates.items():
            for i, s in enumerate(shapes):
                pred, _ = self._nearest(s, skip=(lab, i))
                if is_negative(lab):
                    neg_total += 1
                    neg_ok += int(pred is None or is_negative(pred))
                    continue
                total += 1
                hits += int(pred == lab)
                if len(shapes) > 1:
                    intra.append(self._nearest(s, lab, skip=(lab, i))[1])
                others = [self._nearest(s, o)[1] for o in self.templates if o != lab]
                if others:
                    inter.append(min(others))
        q = {"acierto_dejando_uno_fuera": round(hits / total, 2) if total else None,
             "ventana_s": round(self.window_s, 2),
             "ejemplos": {lab: len(v) for lab, v in self.templates.items()}}
        if neg_total:
            q["otros_rechazados"] = round(neg_ok / neg_total, 2)
        if intra and inter:
            q["separacion"] = round(float(np.median(inter) / max(np.median(intra), 1e-6)), 2)
        return q

    def classify(self, seg: np.ndarray, thr: float) -> tuple[str | None, float]:
        feat = self._features(seg, thr)
        lab, d = self._nearest(feat)
        if lab is None or d > self.max_dist or is_negative(lab):
            return None, d
        others = [self._nearest(feat, o)[1] for o in self.templates if o != lab]
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
                    self.classified = False
                    self.buf = [d for _, d in self.recent]
                    self.buf_t = [ts for ts, _ in self.recent]
                    ev.append({"kind": "start", "t": t})
            else:
                self.above_since = None
            return ev
        self.buf.append(delta)
        self.buf_t.append(t)
        if not self.classified and t - self.started >= self.window_s:
            # Decide con una ventana fija desde el inicio, igual que al entrenar
            arr = np.array(self.buf)
            n_after = sum(1 for ts in self.buf_t if ts >= self.started)
            seg = onset_window(arr, thr, n_after)
            self.classified = True
            if seg is not None:
                lab, d = self.classify(seg, thr)
                self.dist = round(d, 3)
                if lab is not None:
                    self.count += 1
                    self.last = lab
                ev.append({"kind": "trajectory", "t": t, "label": lab, "dist": self.dist})
        if mag < thr / 2:
            if self.below_since is None:
                self.below_since = t
            if t - self.below_since >= self.min_off and self.classified:
                self.active, self.above_since = False, None
                self.buf, self.buf_t, self.recent = [], [], deque()
        else:
            self.below_since = None
            if self.classified and t - self.started > self.max_len:
                # El iman quedo en otra posicion: esa pasa a ser el reposo (Bank lo hace con "drift")
                self.active, self.above_since = False, None
                self.buf, self.buf_t, self.recent = [], [], deque()
                ev.append({"kind": "drift", "t": t})
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
                "otros": sum(len(v) for k, v in self.templates.items() if is_negative(k)),
                "count": self.hits, "last": self.target if self.hits else None,
                "signal": round(self.signal, 3), "threshold": round(self.threshold(noise), 3)}
