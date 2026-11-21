"""MagneSense, fase 2: detectores entrenables con pocos ejemplos.

Tres tipos, todos sobre el vector del magnetometro (uT):

  EventDetector   gesto puntual (contraccion, toque). Clasifica corto/largo/doble.
  RhythmDetector  algo periodico (respiracion, temblor). Frecuencia y aviso de pausa.
  StateDetector   en que posicion esta algo (puerta abierta/cerrada, dedo estirado/recogido).

Todos comparten un Pipeline que suaviza y sigue la linea base. La "direccion
aprendida" (DirectionModel) sale de 3 ejemplos: el detector de eventos mira solo
la proyeccion del cambio sobre esa direccion y descarta cambios que vienen de
otro lado (un notebook que se mueve, llaves, etc).

Solo usa numpy, para que sea facil de instalar y correr en vivo.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

import numpy as np


# ---------------------------------------------------------------------------
# Preprocesamiento: suavizado + linea base adaptativa
# ---------------------------------------------------------------------------

class Pipeline:
    """Entrega para cada lectura el vector suavizado y el cambio respecto al reposo.

    La linea base solo se mueve en reposo. Si hay una direccion aprendida, el
    componente fuera de esa direccion se sigue mas rapido (posturas, derivas)
    y el de la direccion mas lento (para no comerse un gesto lento).
    """

    def __init__(self, smooth_tau=0.04, baseline_tau=4.0, offaxis_tau=1.5, calib_seconds=2.0,
                 gyro_moving=0.25, settle_s=0.6):
        self.smooth_tau = smooth_tau
        self.gyro_deadband = 0.03
        self.gyro_moving = gyro_moving   # rad/s: sobre esto el telefono "se esta moviendo"
        self.settle_s = settle_s         # s quieto tras moverse antes de volver a detectar
        self.baseline_tau = baseline_tau
        self.offaxis_tau = offaxis_tau
        self.calib_seconds = calib_seconds
        self.direction: np.ndarray | None = None
        self.reset()

    def reset(self):
        self.smooth = None
        self.baseline = None
        self.noise = 0.0
        self.hf_noise = 0.0          # ruido del sensor medido con diferencias sucesivas
        self._last_raw = None
        self.last_t = None
        self._calib: list[np.ndarray] = []
        self._calib_t0 = None
        self.hold = False            # True mientras un detector esta activo
        # Giroscopio: R lleva vectores del marco actual del telefono al marco
        # de referencia (el de la calibracion). Asi el campo de la Tierra queda
        # fijo aunque el telefono gire.
        self.R = np.eye(3)
        self.gyro_t = None
        self.gyro_seen = False
        self.omega = 0.0
        self.moving_until = -1e18
        self.moved = False           # hubo giro desde la ultima vez que se quedo quieto

    def gyro(self, t: float, w):
        """Integra una lectura del giroscopio (rad/s, marco del telefono)."""
        w = np.asarray(w, dtype=float)
        self.gyro_seen = True
        self.omega = float(np.linalg.norm(w))
        if self.gyro_t is not None:
            dt = min(max(t - self.gyro_t, 0.0), 0.2)
            ang = self.omega * dt
            # Zona muerta: bajo ~1.7 grados/s no integrar, para que el ruido y
            # el sesgo del giroscopio no giren de a poco el campo de la Tierra.
            if self.omega > self.gyro_deadband and ang > 1e-9:
                k = w / self.omega
                K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
                self.R = self.R @ (np.eye(3) + math.sin(ang) * K + (1 - math.cos(ang)) * K @ K)
        self.gyro_t = t
        if self.omega > self.gyro_moving:
            self.moving_until = t + self.settle_s
            self.moved = True

    def phone_moving(self, t: float) -> bool:
        return t < self.moving_until
    @property
    def calibrating(self) -> bool:
        return self.baseline is None

    def recalibrate(self):
        self.R = np.eye(3)
        self.baseline = None
        self._calib = []
        self._calib_t0 = None

    def step(self, t: float, v) -> tuple[np.ndarray, np.ndarray | None, float]:
        """Devuelve (suavizado, delta o None si calibra, dt)."""
        v = self.R @ np.asarray(v, dtype=float)    # compensar giro del telefono
        dt = 0.0 if self.last_t is None else min(max(t - self.last_t, 0.0), 0.5)
        self.last_t = t
        if self._last_raw is not None:
            d2 = float(((v - self._last_raw) ** 2).sum()) / 2
            self.hf_noise = math.sqrt(self.hf_noise ** 2 + 0.01 * (d2 - self.hf_noise ** 2)) \
                if self.hf_noise else math.sqrt(d2)
        self._last_raw = v
        if self.smooth is None:
            self.smooth = v.copy()
        else:
            a = dt / (self.smooth_tau + dt) if dt > 0 else 1.0
            self.smooth += a * (v - self.smooth)

        if self.baseline is None:
            if self._calib_t0 is None:
                self._calib_t0 = t
            self._calib.append(self.smooth.copy())
            if t - self._calib_t0 >= self.calib_seconds and len(self._calib) >= 10:
                arr = np.array(self._calib)
                self.baseline = arr.mean(axis=0)
                self.noise = float(np.sqrt(((arr - self.baseline) ** 2).sum(axis=1).mean()))
                self._calib = []
            return self.smooth, None, dt

        if self.moved and not self.phone_moving(t):
            # El telefono giro y ya se quedo quieto: lo que quede (iman en otra
            # posicion relativa, deriva del giroscopio) pasa a ser el nuevo reposo.
            self.baseline = self.smooth.copy()
            self.moved = False
        delta = self.smooth - self.baseline
        mag = float(np.linalg.norm(delta))
        rest = (not self.hold) and not self.phone_moving(t) and mag < max(6 * self.noise, 1.0) / 2
        if rest and dt > 0:
            if self.direction is None:
                self.baseline += (dt / self.baseline_tau) * delta
            else:
                u = self.direction
                along = (delta @ u) * u
                off = delta - along
                self.baseline += (dt / self.baseline_tau) * along + (dt / self.offaxis_tau) * off
            a = dt / self.baseline_tau
            self.noise = math.sqrt(self.noise ** 2 + a * (mag ** 2 - self.noise ** 2))
        return self.smooth, delta, dt


# ---------------------------------------------------------------------------
# Direccion aprendida
# ---------------------------------------------------------------------------

@dataclass
class DirectionModel:
    u: np.ndarray                    # vector unitario
    peak: float                      # mediana de la proyeccion maxima en los ejemplos (uT)
    min_cos: float = 0.6             # cuanto debe parecerse la direccion del cambio

    @classmethod
    def fit(cls, examples: list[np.ndarray]) -> "DirectionModel":
        """examples: lista de arrays (n, 3) con el delta (B - reposo) de cada ejemplo."""
        peaks = []
        for ex in examples:
            ex = np.asarray(ex, dtype=float)
            if len(ex) == 0:
                continue
            i = int(np.argmax(np.linalg.norm(ex, axis=1)))
            peaks.append(ex[i])
        if not peaks:
            raise ValueError("sin ejemplos")
        P = np.array(peaks)
        # Alinear signos con el primer ejemplo y promediar direcciones
        units = P / np.maximum(np.linalg.norm(P, axis=1, keepdims=True), 1e-9)
        ref = units[0]
        units = np.where((units @ ref)[:, None] < 0, -units, units)
        u = units.mean(axis=0)
        u /= max(np.linalg.norm(u), 1e-9)
        proj = P @ u
        return cls(u=u, peak=float(np.median(np.abs(proj))))

    def consistency(self, examples: list[np.ndarray]) -> float:
        """Coseno minimo entre la direccion y cada ejemplo (1 = identicos)."""
        cs = []
        for ex in examples:
            ex = np.asarray(ex, dtype=float)
            i = int(np.argmax(np.linalg.norm(ex, axis=1)))
            p = ex[i]
            cs.append(abs(p @ self.u) / max(np.linalg.norm(p), 1e-9))
        return float(min(cs)) if cs else 0.0

    def to_dict(self):
        return {"u": [round(float(x), 4) for x in self.u], "peak": round(self.peak, 3),
                "min_cos": self.min_cos}


# ---------------------------------------------------------------------------
# Detector de eventos
# ---------------------------------------------------------------------------

class EventDetector:
    """Gesto puntual con duracion minima, histeresis y clasificacion.

    Eventos que emite (dict con "kind"):
      start            empezo un gesto valido (paso la duracion minima)
      end              termino (incluye "duration")
      short / long     gesto resuelto (corto o largo segun long_s)
      double           dos cortos separados por menos de double_gap
    """

    kind = "event"

    def __init__(self, name="evento", direction: DirectionModel | None = None,
                 k=6.0, floor=1.0, min_on=0.15, min_off=0.10, long_s=0.8,
                 double_gap=0.5, stuck_after=6.0, peak_frac=0.4):
        self.name = name
        self.direction = direction
        self.k, self.floor = k, floor
        self.min_on, self.min_off = min_on, min_off
        self.long_s, self.double_gap = long_s, double_gap
        self.stuck_after = stuck_after
        self.peak_frac = peak_frac
        self.reset()

    def reset(self):
        self.active = False
        self.signal = 0.0
        self.above_since = None
        self.below_since = None
        self.active_since = None
        self.pending_short_end = None   # para detectar doble
        self.count = 0
        self.last_gesture = None

    def threshold(self, noise: float) -> float:
        thr = max(self.k * noise, self.floor)
        if self.direction is not None:
            thr = max(thr, self.peak_frac * self.direction.peak)
        return thr

    def _signal(self, delta: np.ndarray, raw_delta: np.ndarray) -> tuple[float, float]:
        if self.direction is None:
            return float(np.linalg.norm(delta)), float(np.linalg.norm(raw_delta))
        u = self.direction.u
        s = float(delta @ u)
        mag = float(np.linalg.norm(delta))
        if mag > 1e-9 and abs(s) / mag < self.direction.min_cos:
            s = 0.0                      # cambio en otra direccion: no cuenta
        # el signo importa: el gesto aprendido empuja hacia +u
        return max(s, 0.0), max(float(raw_delta @ u), 0.0)

    def step(self, t: float, delta: np.ndarray, raw_delta: np.ndarray, noise: float) -> list[dict]:
        ev: list[dict] = []
        sig, raw = self._signal(delta, raw_delta)
        self.signal = sig
        thr = self.threshold(noise)

        # Resolver un corto pendiente si ya paso la ventana de doble
        if self.pending_short_end is not None and not self.active and self.above_since is None \
                and t - self.pending_short_end > self.double_gap:
            ev.append(self._gesture("short", t))
            self.pending_short_end = None

        if not self.active:
            if sig > thr and raw > thr / 2:
                if self.above_since is None:
                    self.above_since = t
                if t - self.above_since >= self.min_on:
                    self.active = True
                    self.active_since = self.above_since
                    self.below_since = None
                    ev.append({"kind": "start", "t": t})
            else:
                self.above_since = None
        else:
            if sig < thr / 2:
                if self.below_since is None:
                    self.below_since = t
                if t - self.below_since >= self.min_off:
                    dur = self.below_since - self.active_since
                    self.active = False
                    self.above_since = None
                    ev.append({"kind": "end", "t": t, "duration": round(dur, 3)})
                    if dur >= self.long_s:
                        if self.pending_short_end is not None:
                            ev.append(self._gesture("short", t))
                            self.pending_short_end = None
                        ev.append(self._gesture("long", t, dur))
                    elif self.pending_short_end is not None:
                        self.pending_short_end = None
                        ev.append(self._gesture("double", t))
                    else:
                        self.pending_short_end = t
            else:
                self.below_since = None
                if t - self.active_since >= self.stuck_after:
                    self.active = False
                    self.above_since = self.below_since = None
                    self.pending_short_end = None
                    ev.append({"kind": "end", "t": t, "duration": round(t - self.active_since, 3)})
                    ev.append({"kind": "stuck", "t": t})
        return ev

    def _gesture(self, kind, t, dur=None):
        self.count += 1
        self.last_gesture = kind
        d = {"kind": kind, "t": t}
        if dur is not None:
            d["duration"] = round(dur, 3)
        return d

    def status(self, noise: float) -> dict:
        return {"name": self.name, "type": self.kind, "active": self.active,
                "signal": round(self.signal, 3), "threshold": round(self.threshold(noise), 3),
                "count": self.count, "last": self.last_gesture,
                "direction": self.direction.to_dict() if self.direction else None}


# ---------------------------------------------------------------------------
# Detector de ritmo
# ---------------------------------------------------------------------------

class RhythmDetector:
    """Frecuencia dominante en una banda y aviso de pausa.

    Usa el vector suavizado (no el delta) y le quita la tendencia en la
    ventana, asi la linea base no se come la respiracion. Proyecta sobre el
    eje de mayor variacion (o la direccion aprendida, si hay).
    Bandas tipicas: respiracion 0.1-0.7 Hz, temblor 3-12 Hz.
    """

    kind = "rhythm"

    def __init__(self, name="ritmo", band=(0.1, 0.7), window=20.0, pause_s=10.0,
                 fs=20.0, min_amp=None, k=2.0, update_every=0.5, direction=None):
        self.name = name
        self.band = band
        self.window = window
        self.pause_s = pause_s
        self.fs = max(fs, 2.5 * band[1])
        self.min_amp = min_amp
        self.k = k
        self.update_every = update_every
        self.direction = direction
        self.buf: deque[tuple[float, float, float, float]] = deque()
        self.reset()

    def reset(self):
        self.buf.clear()
        self.freq = None
        self.amp = 0.0
        self.present = False
        self.paused = False
        self.ever_present = False
        self.last_update = None
        self.pauses = 0

    def amp_threshold(self, noise):
        return self.min_amp if self.min_amp is not None else max(self.k * noise, 0.3)

    def step(self, t: float, smooth: np.ndarray, noise: float) -> list[dict]:
        """noise: ruido del sensor (Pipeline.hf_noise), no el de la calibracion."""
        self.buf.append((t, *map(float, smooth)))
        while self.buf and t - self.buf[0][0] > self.window:
            self.buf.popleft()
        if self.last_update is not None and t - self.last_update < self.update_every:
            return []
        self.last_update = t
        arr = np.array(self.buf)
        if len(arr) < 8 or arr[-1, 0] - arr[0, 0] < min(self.window * 0.5, 4.0 / self.band[0]):
            return []
        ev: list[dict] = []
        sig = _project(arr[:, 1:], self.direction)
        tt = arr[:, 0]
        grid = np.arange(tt[0], tt[-1], 1.0 / self.fs)
        if len(grid) < 8:
            return []
        y = np.interp(grid, tt, sig)
        y = y - np.polyval(np.polyfit(grid - grid[0], y, 1), grid - grid[0])

        # Frecuencia dominante (FFT con ventana de Hann y relleno)
        n = len(y)
        nfft = 1 << int(math.ceil(math.log2(n * 4)))
        spec = np.abs(np.fft.rfft(y * np.hanning(n), nfft)) ** 2
        freqs = np.fft.rfftfreq(nfft, 1.0 / self.fs)
        m = (freqs >= self.band[0]) & (freqs <= self.band[1])
        total = spec[1:].sum()
        if m.any() and total > 0:
            i = int(np.argmax(np.where(m, spec, 0)))
            band_ratio = spec[m].sum() / total
            self.freq = float(freqs[i])
        else:
            band_ratio = 0.0
            self.freq = None

        # Amplitud reciente (pico a pico / 2 en los ultimos pause_s)
        recent = y[grid >= grid[-1] - self.pause_s]
        self.amp = float((np.percentile(recent, 95) - np.percentile(recent, 5)) / 2) if len(recent) else 0.0
        thr = self.amp_threshold(noise)
        was_present = self.present
        self.present = band_ratio > 0.4 and self.amp > thr
        if self.present:
            self.ever_present = True
        if self.present and not was_present:
            ev.append({"kind": "rhythm_start", "t": t, "freq": self.freq})
        # Pausa: antes habia ritmo y en los ultimos pause_s la amplitud cayo
        if self.ever_present and not self.paused and self.amp < thr:
            self.paused = True
            self.pauses += 1
            ev.append({"kind": "pause", "t": t})
        elif self.paused and self.present:
            self.paused = False
            ev.append({"kind": "resume", "t": t, "freq": self.freq})
        return ev

    def status(self, noise: float) -> dict:
        return {"name": self.name, "type": self.kind, "active": self.paused,
                "present": self.present, "paused": self.paused,
                "freq_hz": round(self.freq, 3) if self.freq else None,
                "per_min": round(self.freq * 60, 1) if self.freq else None,
                "amp": round(self.amp, 3), "threshold": round(self.amp_threshold(noise), 3),
                "band": list(self.band), "count": self.pauses}


def _project(vecs: np.ndarray, direction: DirectionModel | None) -> np.ndarray:
    if direction is not None:
        return vecs @ direction.u
    c = vecs - vecs.mean(axis=0)
    if len(c) < 3:
        return c[:, 0]
    _, _, vt = np.linalg.svd(c, full_matrices=False)
    return c @ vt[0]


# ---------------------------------------------------------------------------
# Detector de estado
# ---------------------------------------------------------------------------

class StateDetector:
    """Centroide mas cercano sobre el vector suavizado, con rechazo y espera.

    Entrenamiento: {"abierta": [array(n,3), ...], "cerrada": [...]} con el
    vector suavizado (absoluto, no delta) de cada ejemplo.
    """

    kind = "state"

    def __init__(self, name="estado", hold_s=0.3, reject_factor=3.0, min_radius=1.5):
        self.name = name
        self.hold_s = hold_s
        self.reject_factor = reject_factor
        self.min_radius = min_radius
        self.labels: list[str] = []
        self.centroids = np.zeros((0, 3))
        self.radius = np.zeros(0)
        self.reset()

    def reset(self):
        self.state = None
        self.candidate = None
        self.candidate_since = None
        self.changes = 0
        self.dist = None

    def fit(self, examples: dict[str, list[np.ndarray]]):
        labels, cents, rads = [], [], []
        for lab, exs in examples.items():
            pts = np.concatenate([np.asarray(e, float) for e in exs if len(e)], axis=0)
            c = pts.mean(axis=0)
            spread = np.percentile(np.linalg.norm(pts - c, axis=1), 90)
            labels.append(lab)
            cents.append(c)
            rads.append(max(self.reject_factor * spread, self.min_radius))
        if len(labels) < 2:
            raise ValueError("se necesitan al menos dos estados")
        self.labels = labels
        self.centroids = np.array(cents)
        self.radius = np.array(rads)
        # Si dos estados estan muy juntos, achicar radios para que no se pisen
        d = np.linalg.norm(self.centroids[:, None] - self.centroids[None], axis=2)
        np.fill_diagonal(d, np.inf)
        self.radius = np.minimum(self.radius, d.min(axis=1) * 0.75)
        self.reset()
        return self

    def separation(self) -> float:
        """Distancia minima entre estados / radio tipico (>2 = bien separados)."""
        d = np.linalg.norm(self.centroids[:, None] - self.centroids[None], axis=2)
        np.fill_diagonal(d, np.inf)
        return float(d.min() / max(np.median(self.radius) / self.reject_factor, 1e-9))

    def classify(self, v: np.ndarray) -> str | None:
        d = np.linalg.norm(self.centroids - v, axis=1)
        i = int(np.argmin(d))
        self.dist = float(d[i])
        return self.labels[i] if d[i] <= self.radius[i] else None

    def step(self, t: float, smooth: np.ndarray) -> list[dict]:
        if not self.labels:
            return []
        lab = self.classify(np.asarray(smooth, float))
        if lab != self.candidate:
            self.candidate, self.candidate_since = lab, t
        ev = []
        if lab != self.state and t - self.candidate_since >= self.hold_s:
            prev, self.state = self.state, lab
            self.changes += 1
            ev.append({"kind": "state", "t": t, "state": lab, "prev": prev})
        return ev

    def status(self, noise: float) -> dict:
        return {"name": self.name, "type": self.kind, "state": self.state,
                "active": self.state is not None, "labels": self.labels,
                "dist": round(self.dist, 3) if self.dist is not None else None,
                "count": self.changes}


# ---------------------------------------------------------------------------
# Banco de detectores: lo que usa el servidor y la evaluacion offline
# ---------------------------------------------------------------------------

@dataclass
class Bound:
    det: object
    action: str = "toggle"           # toggle | hold | on | none
    trigger: str = "any"             # any (al empezar) | short | long | double | pause | estado


@dataclass
class Bank:
    pipeline: Pipeline = field(default_factory=Pipeline)
    detectors: dict = field(default_factory=dict)   # name -> Bound

    def add(self, det, action="toggle", trigger=None):
        if trigger is None:
            trigger = {"event": "any", "rhythm": "pause", "state": ""}[det.kind]
        self.detectors[det.name] = Bound(det, action, trigger)
        if isinstance(det, EventDetector) and det.direction is not None:
            self.pipeline.direction = det.direction.u

    def remove(self, name):
        self.detectors.pop(name, None)
        dirs = [b.det.direction.u for b in self.detectors.values()
                if isinstance(b.det, EventDetector) and b.det.direction is not None]
        self.pipeline.direction = dirs[0] if dirs else None

    def gyro(self, t: float, w):
        self.pipeline.gyro(t, w)

    def step(self, t: float, v) -> list[dict]:
        """Procesa una lectura cruda. Devuelve eventos con "detector" y "action"."""
        p = self.pipeline
        smooth, delta, _ = p.step(t, v)
        raw = p.R @ np.asarray(v, float)
        out: list[dict] = []
        if delta is None:
            return out
        raw_delta = raw - p.baseline
        moving = p.phone_moving(t)
        if moving:
            # Si se mueve el telefono, el cambio no es del iman: no detectar
            delta = np.zeros(3)
            raw_delta = np.zeros(3)
        any_active = False
        for name, b in self.detectors.items():
            d = b.det
            if isinstance(d, EventDetector):
                ev = d.step(t, delta, raw_delta, p.noise)
                any_active |= d.active
            elif isinstance(d, RhythmDetector):
                ev = d.step(t, smooth, p.hf_noise)
            else:
                ev = d.step(t, smooth)
            for e in ev:
                e["detector"] = name
                e["action"] = self._action(b, e)
                out.append(e)
        p.hold = any_active
        return out

    @staticmethod
    def _action(b: Bound, e: dict) -> str | None:
        k = e["kind"]
        if b.action == "none":
            return None
        if b.det.kind == "state":
            if k != "state":
                return None
            if b.trigger:
                return "on" if e["state"] == b.trigger else "off"
            return "toggle"
        if b.action == "hold":
            if k == "start" or (k == "pause"):
                return "on"
            if k == "end" or k == "resume":
                return "off"
            return None
        if k == b.trigger or (b.trigger == "any" and k == "start"):
            return "on" if b.action == "on" else "toggle"
        return None

    def status(self) -> dict:
        p = self.pipeline
        return {"calibrating": p.calibrating, "noise": round(p.noise, 4),
                "sensor_noise": round(p.hf_noise, 4),
                "gyro": p.gyro_seen, "phone_moving": p.phone_moving(p.last_t or 0.0),
                "detectors": [dict(b.det.status(p.hf_noise if b.det.kind == "rhythm" else p.noise),
                                   action=b.action, trigger=b.trigger)
                              for b in self.detectors.values()]}


# ---------------------------------------------------------------------------
# Utilidades para ejemplos grabados
# ---------------------------------------------------------------------------

def segments(labels: list[str]) -> list[tuple[int, int, str]]:
    """Tramos contiguos con la misma etiqueta no vacia: [(inicio, fin_exclusivo, etiqueta)]."""
    out, start, cur = [], None, ""
    for i, lab in enumerate(list(labels) + [""]):
        lab = lab or ""
        if lab != cur:
            if cur:
                out.append((start, i, cur))
            start, cur = i, lab
    return out


def deltas_for(raw: np.ndarray, t: np.ndarray, seg: tuple[int, int, str], pad=1.0) -> np.ndarray:
    """Delta de un ejemplo: suavizado menos el promedio del segundo previo."""
    i0, i1, _ = seg
    pre = (t >= t[i0] - pad) & (t < t[i0])
    base = raw[pre].mean(axis=0) if pre.any() else raw[max(i0 - 10, 0):i0 + 1].mean(axis=0)
    return raw[i0:i1] - base
