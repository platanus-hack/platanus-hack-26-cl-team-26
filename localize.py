"""Posicion 3D del iman respecto al sensor del telefono.

Modelo: el iman es un dipolo magnetico m ubicado en p (metros, ejes del
telefono: x a la derecha, y hacia arriba de la pantalla, z saliendo de la
pantalla; el origen es el magnetometro). El campo en el sensor es

    B(p) = 1e-7 * (3 (m·r̂) r̂ - m) / |r|^3,   r = -p      (Tesla)

Con un solo magnetometro hay 3 mediciones, asi que se fija la orientacion del
iman (debe mirar siempre hacia el mismo lado: pegado en la uña o en un anillo)
y se calcula la posicion (3 incognitas). Pasos:

  1. Sin iman cerca: se guarda el campo de la Tierra y del telefono (base).
  2. Iman a una distancia conocida justo sobre el sensor (0, 0, d): como B es
     lineal en m, se despeja m (fuerza y orientacion del iman) exactamente.
  3. En vivo: se busca la p que explica el campo medido (Gauss-Newton
     amortiguado, partiendo de la ultima posicion).

"confianza" compara el campo medido con el del modelo en la posicion hallada:
si el iman se inclina, esta muy cerca (no es un dipolo ideal o satura el
sensor) o hay metal cerca, baja. Simetria: p y -p dan exactamente el mismo
campo. Se elige la que esta mas cerca de la posicion anterior (el iman se mueve
de forma continua); solo al empezar se elige el lado de la pantalla (z > 0).
Elegir siempre z > 0 fallaba con el iman al lado del celular, a la altura de la
mesa: queda un poco bajo el sensor y se "reflejaba" al lado contrario.

Solo usa numpy.
"""

from __future__ import annotations

from collections import deque

import numpy as np

K = 1e-7 * 1e6           # mu0/4pi en uT·m/(A·m^2)
MIN_DIST = 0.008         # m; mas cerca el modelo de dipolo ya no sirve
MAX_DIST = 0.25          # m


def dipole_matrix(p: np.ndarray) -> np.ndarray:
    """Matriz G(p) tal que B = G(p) @ m (uT, con p en metros y m en A·m^2)."""
    r = -np.asarray(p, float)
    d = float(np.linalg.norm(r))
    rh = r / d
    return K * (3 * np.outer(rh, rh) - np.eye(3)) / d ** 3


def field(p: np.ndarray, m: np.ndarray) -> np.ndarray:
    return dipole_matrix(p) @ np.asarray(m, float)


def solve_position(b: np.ndarray, m: np.ndarray, p0: np.ndarray, iters: int = 25) -> tuple[np.ndarray, float]:
    """Posicion p que mejor explica el campo b (uT). Devuelve (p, error relativo)."""
    p = np.array(p0, float)
    lam = 1e-3
    err = np.linalg.norm(field(p, m) - b)
    for _ in range(iters):
        r = field(p, m) - b
        J = np.empty((3, 3))
        h = 1e-6
        for k in range(3):
            e = np.zeros(3)
            e[k] = h
            J[:, k] = (field(p + e, m) - field(p - e, m)) / (2 * h)
        A = J.T @ J
        step = np.linalg.solve(A + lam * np.diag(np.diag(A) + 1e-12), -J.T @ r)
        cand = p + step
        dist = np.linalg.norm(cand)
        if dist < MIN_DIST:
            cand *= MIN_DIST / dist
        new_err = np.linalg.norm(field(cand, m) - b)
        if new_err < err:
            p, err, lam = cand, new_err, max(lam / 3, 1e-7)
            if np.linalg.norm(step) < 1e-7:
                break
        else:
            lam *= 4
    return p, float(err / max(np.linalg.norm(b), 1e-9))


class Tracker:
    """Estado del rastreo: base sin iman, momento del iman y ultima posicion."""

    def __init__(self):
        self.recent: deque[np.ndarray] = deque(maxlen=40)    # ultimos vectores suavizados
        self.base: np.ndarray | None = None
        self.noise = 0.2                     # uT, medido en el paso 1 (sin iman)
        self.m: np.ndarray | None = None
        self.ref_cm: float | None = None
        self.p: np.ndarray | None = None
        self.last: dict = {"estado": "sin_base"}
        self.trail: deque[list[float]] = deque(maxlen=60)

    def reset(self):
        self.__init__()

    # --- calibracion --------------------------------------------------------
    def _mean_recent(self, n: int = 15) -> np.ndarray:
        """Promedio de las ultimas lecturas; exige que esten quietas (iman sin moverse)."""
        if len(self.recent) < n:
            raise ValueError("faltan datos del telefono: espera a que lleguen lecturas")
        arr = np.array(self.recent)[-n:]
        mean = arr.mean(axis=0)
        spread = float(np.linalg.norm(arr.std(axis=0)))
        if spread > max(1.0, 0.02 * np.linalg.norm(mean)):
            raise ValueError(f"las lecturas se estan moviendo ({spread:.1f} uT): deja el iman y el "
                             "celular quietos un segundo y vuelve a intentar")
        return mean

    def set_base(self) -> dict:
        """Paso 1: el iman lejos (> 30 cm). Guarda el campo de la Tierra y del telefono."""
        self.base = self._mean_recent()
        arr = np.array(self.recent)[-15:]
        self.noise = max(float(np.linalg.norm(arr.std(axis=0))), 0.05)
        self.m = None
        self.p = None
        self.trail.clear()
        self.last = {"estado": "sin_iman_calibrado"}
        return {"base_uT": [round(float(v), 2) for v in self.base]}

    def calibrate(self, dist_cm: float) -> dict:
        """Paso 2: iman a dist_cm justo sobre el sensor, mirando como se va a usar."""
        if self.base is None:
            raise ValueError("primero mide sin iman (paso 1)")
        if not 1.0 <= dist_cm <= 15.0:
            raise ValueError("la distancia de calibracion debe estar entre 1 y 15 cm")
        b = self._mean_recent() - self.base
        if np.linalg.norm(b) < 3.0:
            raise ValueError(f"el iman casi no cambia el campo ({np.linalg.norm(b):.1f} uT): "
                             "acercalo justo sobre el punto del sensor")
        p_ref = np.array([0.0, 0.0, dist_cm / 100])
        self.m = np.linalg.solve(dipole_matrix(p_ref), b)
        self.ref_cm = dist_cm
        self.p = p_ref.copy()
        self.trail.clear()
        self.last = {"estado": "rastreando"}
        strength = float(np.linalg.norm(self.m))
        tilt = float(np.degrees(np.arccos(abs(self.m[2]) / max(strength, 1e-12))))
        return {"momento_Am2": round(strength, 4), "inclinacion_grados": round(tilt, 1),
                "campo_uT": round(float(np.linalg.norm(b)), 1)}

    # --- en vivo -------------------------------------------------------------
    def push(self, smooth: np.ndarray):
        """Recibe el vector suavizado (ya compensado por el giro del telefono)."""
        self.recent.append(np.asarray(smooth, float).copy())

    def update(self, noise: float | None = None) -> dict:
        """noise: se ignora si ya se midio sin iman (el ruido del pipeline se infla con
        los saltos del iman cerca y haria creer que esta lejos)."""
        noise = self.noise if self.base is not None else (noise or 0.2)
        if self.base is None:
            return {"estado": "sin_base"}
        if self.m is None:
            return {"estado": "sin_iman_calibrado"}
        if not self.recent:
            return self.last
        b = self.recent[-1] - self.base
        bmag = float(np.linalg.norm(b))
        if bmag < max(10 * noise, 1.5):
            self.last = {"estado": "lejos", "campo_uT": round(bmag, 2)}
            return self.last
        # Inicial: la posicion anterior, o la distancia que da la intensidad sobre el eje
        if self.p is None:
            d = (2 * K * np.linalg.norm(self.m) / bmag) ** (1 / 3)
            self.p = np.array([0.0, 0.0, min(max(d, MIN_DIST), MAX_DIST)])   # lado de la pantalla
        prev = self.p
        p, rel = solve_position(b, self.m, prev)
        # p y -p explican igual el campo: quedarse con la mas cercana a la anterior
        if np.linalg.norm(-p - prev) < np.linalg.norm(p - prev):
            p = -p
        if np.linalg.norm(p) > MAX_DIST:
            self.last = {"estado": "lejos", "campo_uT": round(bmag, 2)}
            return self.last
        self.p = p
        conf = max(0.0, 1.0 - 5 * rel)          # 1 = el modelo explica todo el campo
        cm = [round(float(v) * 100, 2) for v in p]
        self.trail.append(cm)
        self.last = {"estado": "rastreando", "x": cm[0], "y": cm[1], "z": cm[2],
                     "dist": round(float(np.linalg.norm(p)) * 100, 2),
                     "confianza": round(conf, 2), "campo_uT": round(bmag, 1)}
        return self.last

    def status(self) -> dict:
        return dict(self.last, ref_cm=self.ref_cm, trail=list(self.trail)[-30:],
                    calibrado=self.m is not None, base=self.base is not None)
