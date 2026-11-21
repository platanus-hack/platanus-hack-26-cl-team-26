"""Analisis de los ejemplos grabados: ¿se vio el movimiento? ¿se distinguen?

Lo usa el servidor para:
  - rechazar ejemplos sin movimiento antes de crear un detector,
  - elegir solo el modelo que mejor separa los movimientos grabados,
  - explicarle al agente (Claude) que paso, para que lo diga en palabras simples.

Dos modelos posibles para un movimiento:
  direccion  el gesto empuja el iman siempre hacia el mismo lado (DirectionModel).
             Rapido y robusto; sirve si cada movimiento empuja hacia un lado distinto.
  patron     el movimiento se reconoce por su forma en el tiempo (trajectory.py).
             Sirve cuando dos movimientos empujan parecido pero en otro orden
             (girar a un lado u otro, barrer de izquierda a derecha o al reves).
"""

from __future__ import annotations

import numpy as np

from detectors import DirectionModel
from trajectory import TrajectoryDetector

MIN_SEEN = 2            # ejemplos que deben verse para crear un detector
GOOD_CONSISTENCY = 0.8  # DirectionModel: parecido minimo entre ejemplos
MAX_COS_BETWEEN = 0.6   # dos movimientos con direcciones mas parecidas que esto se confunden


def threshold(noise: float) -> float:
    """Mismo umbral que usan los detectores: 6 x ruido, minimo 1 uT."""
    return max(6.0 * noise, 1.0)


def example_info(delta: np.ndarray, noise: float, rate: float, moving=None) -> dict:
    """Resumen de un ejemplo: pico, si se vio, si quedo cortado y si el celular se movio."""
    d = np.asarray(delta, float)
    thr = threshold(noise)
    if len(d) == 0:
        return {"pico_uT": 0.0, "se_vio": False, "problema": "ejemplo vacio"}
    mag = np.linalg.norm(d, axis=1)
    i = int(mag.argmax())
    above = np.nonzero(mag > thr)[0]
    out = {"pico_uT": round(float(mag[i]), 2),
           "veces_el_ruido": round(float(mag[i] / max(noise, 1e-3)), 1),
           "se_vio": len(above) >= 3,
           "duracion_s": round(len(d) / rate, 2) if rate else None}
    if out["se_vio"]:
        out["movimiento_s"] = round((above[-1] - above[0] + 1) / rate, 2) if rate else None
        out["cortado_al_final"] = bool(above[-1] >= len(d) - 2)
        out["cortado_al_inicio"] = bool(above[0] <= 1)
        out["direccion"] = [round(float(v), 2) for v in d[i] / max(mag[i], 1e-9)]
    if moving is not None and len(moving):
        out["celular_movido"] = round(float(np.mean(moving)), 2)
    return out


def _problem_text(label: str, exs: list[dict], thr: float) -> str | None:
    n, seen = len(exs), sum(e["se_vio"] for e in exs)
    if n == 0:
        return f"no hay ejemplos de '{label}'"
    if seen < MIN_SEEN or 2 * seen < n:          # menos de la mitad: probablemente accidental
        peak = max((e["pico_uT"] for e in exs), default=0.0)
        return (f"en '{label}' solo {seen} de {n} ejemplos muestran movimiento (el mayor cambio fue "
                f"{peak:.1f} uT y hace falta superar {thr:.1f} uT). Acerca el iman a 2-3 cm del punto "
                f"donde esta el sensor, deja el celular fijo y haz el movimiento apenas empiece la grabacion")
    return None


def analyze(examples: dict[str, list[dict]], noise: float, rate: float) -> dict:
    """examples: {etiqueta: [{"delta": array(n,3), "moving": array(n)?}, ...]}."""
    noise = float(noise or 0.2)
    thr = threshold(noise)
    labels: dict[str, dict] = {}
    seen_deltas: dict[str, list[np.ndarray]] = {}
    for lab, exs in examples.items():
        infos = [example_info(e["delta"], noise, rate, e.get("moving")) for e in exs]
        seen = [np.asarray(e["delta"], float) for e, inf in zip(exs, infos) if inf["se_vio"]]
        seen_deltas[lab] = seen
        notes = []
        cut = sum(1 for inf in infos if inf.get("cortado_al_final"))
        if cut:
            notes.append(f"{cut} ejemplo(s) seguian en movimiento al terminar la grabacion: "
                         "empieza antes o haz el movimiento mas corto")
        moved = sum(1 for inf in infos if inf.get("celular_movido", 0) > 0.2)
        if moved:
            notes.append(f"en {moved} ejemplo(s) se movio el celular: dejalo apoyado y sin tocarlo")
        if 0 < len(exs) - len(seen) and 2 * len(seen) >= len(exs):
            notes.append(f"{len(exs) - len(seen)} de {len(exs)} ejemplos no se vieron y no se usaran")
        info = {"ejemplos": len(exs), "vistos": len(seen), "detalle": infos,
                "problema": _problem_text(lab, infos, thr), "avisos": notes}
        if len(seen) >= MIN_SEEN:
            dm = DirectionModel.fit(seen)
            info["parecido_direccion"] = round(dm.consistency(seen), 2)
            info["_u"] = dm.u
        labels[lab] = info

    # ¿Se distinguen entre si los movimientos?
    pairs = []
    ok = [lab for lab, inf in labels.items() if "_u" in inf]
    for i, a in enumerate(ok):
        for b in ok[i + 1:]:
            cos = float(labels[a]["_u"] @ labels[b]["_u"])
            pair = {"a": a, "b": b, "coseno_direcciones": round(cos, 2)}
            try:
                q = TrajectoryDetector().fit({a: seen_deltas[a], b: seen_deltas[b]}, noise).quality()
                pair["acierto_patron"] = q.get("acierto_dejando_uno_fuera")
                pair["separacion_patron"] = q.get("separacion")
            except ValueError:
                pass
            pairs.append(pair)

    for lab, inf in labels.items():
        if inf["problema"]:
            inf["modelo_sugerido"] = None
            continue
        rivals = [p for p in pairs if lab in (p["a"], p["b"])]
        by_direction = inf.get("parecido_direccion", 0) >= GOOD_CONSISTENCY and all(
            p["coseno_direcciones"] < MAX_COS_BETWEEN for p in rivals)
        inf["modelo_sugerido"] = "direccion" if by_direction else "patron"
        confused = [p for p in rivals if p["coseno_direcciones"] >= MAX_COS_BETWEEN
                    and (p.get("acierto_patron") or 0) < 1.0]
        for p in confused:
            other = p["b"] if p["a"] == lab else p["a"]
            inf["avisos"].append(f"'{lab}' y '{other}' se confunden: haz los dos movimientos mas "
                                 "distintos o regrabalos con mas cuidado")
    for inf in labels.values():
        inf.pop("_u", None)
    return {"ruido_uT": round(noise, 3), "umbral_uT": round(thr, 2), "muestreo_hz": round(rate, 1),
            "etiquetas": labels, "pares": pairs}


def summary(an: dict) -> dict:
    """Version corta para el agente (sin el detalle de cada ejemplo)."""
    out = {"umbral_uT": an["umbral_uT"], "pares": an["pares"], "etiquetas": {}}
    for lab, inf in an["etiquetas"].items():
        out["etiquetas"][lab] = {k: inf.get(k) for k in ("ejemplos", "vistos", "parecido_direccion",
                                                          "modelo_sugerido", "problema", "avisos")}
        out["etiquetas"][lab]["picos_uT"] = [e["pico_uT"] for e in inf["detalle"]]
    return out
