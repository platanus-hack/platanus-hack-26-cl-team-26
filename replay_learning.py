"""Mide el aprendizaje automatico con una sesion real grabada por server.py.

Reproduce data/session_*.csv por el mismo pipeline del servidor (giroscopio
incluido), arma los ejemplos de cada etiqueta igual que /record, entrena como
/train y vuelve a pasar la sesion completa contando cuantas veces se dispara
cada detector dentro de sus propias grabaciones y fuera de ellas.

Uso:
    python replay_learning.py data/session_X.csv
    python replay_learning.py data/session_X.csv --gestos izquierda --otros otros

Las activaciones "fuera" incluyen las pruebas que se hicieron despues de
entrenar (gestos reales) y los movimientos que no debian activar: sirven para
comparar versiones, no son una tasa de error exacta.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter

import numpy as np

import analysis
from detectors import Bank, DirectionModel, EventDetector
from trajectory import PatternDetector


def load(path):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    out = []
    for r in rows:
        if r.get("x"):
            out.append(("m", float(r["t"]), np.array([float(r["x"]), float(r["y"]), float(r["z"])]),
                        r.get("label", ""), r.get("moving") == "1"))
        elif r.get("gx"):
            out.append(("g", float(r["t"]), np.array([float(r["gx"]), float(r["gy"]), float(r["gz"])]),
                        r.get("label", ""), False))
    return out


def collect_examples(rows):
    """Igual que /record: delta = R @ v - linea base al empezar a grabar."""
    bank = Bank()
    p = bank.pipeline
    examples: dict[str, list[dict]] = {}
    cur, base, buf, mov = None, None, [], []
    windows = []
    for kind, t, v, label, moving in rows:
        if kind == "g":
            bank.gyro(t, v)
            continue
        p.step(t, v)
        vr = p.R @ v
        if label and label != cur:
            if cur and buf:
                examples.setdefault(cur, []).append({"delta": np.array(buf), "moving": np.array(mov)})
            cur, buf, mov = label, [], []
            base = p.baseline.copy() if p.baseline is not None else vr
            windows.append([label, t, t])
        if label:
            buf.append(vr - base)
            mov.append(p.phone_moving(t))
            windows[-1][2] = t
        elif cur:
            if buf:
                examples.setdefault(cur, []).append({"delta": np.array(buf), "moving": np.array(mov)})
            cur, buf, mov = None, [], []
    rate = sum(1 for r in rows if r[0] == "m") / max(rows[-1][1] - rows[0][1], 1e-9)
    return examples, p.noise, rate, windows


def train(examples, noise, rate, gestures, model=None):
    an = analysis.analyze(examples, noise, rate)
    seen = {lab: [e["delta"] for e, i in zip(examples[lab], inf["detalle"]) if i["se_vio"]]
            for lab, inf in an["etiquetas"].items() if inf["vistos"]}
    dets = {}
    for g in gestures:
        inf = an["etiquetas"][g]
        m = model or inf["modelo_sugerido"] or "patron"
        if m == "direccion":
            dets[g] = EventDetector(g, direction=DirectionModel.fit(seen[g]))
        else:
            dets[g] = PatternDetector(g, target=g).fit(seen, noise, rate)
        dets[g].chosen = m
    return an, dets


def replay(rows, dets, windows):
    bank = Bank()
    for name, d in dets.items():
        bank.add(d, action="none", trigger="any")
    fires = {name: Counter() for name in dets}
    for kind, t, v, label, _ in rows:
        if kind == "g":
            bank.gyro(t, v)
            continue
        for e in bank.step(t, v):
            if e["kind"] != "start":
                continue
            inside = next((w[0] for w in windows if w[1] - 0.5 <= t <= w[2] + 1.0), None)
            fires[e["detector"]]["en '" + inside + "'" if inside else "fuera"] += 1
    return fires


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--gestos", nargs="*", help="etiquetas a entrenar (por defecto todas menos otros)")
    ap.add_argument("--modelo", choices=["direccion", "patron"])
    ap.add_argument("--otros", nargs="*", default=[],
                    help="etiquetas grabadas que deben tratarse como 'otros' (contraejemplos)")
    a = ap.parse_args()
    rows = load(a.csv)
    examples, noise, rate, windows = collect_examples(rows)
    for lab in a.otros:                       # p. ej. "mover recto" como contraejemplo de "girar"
        examples.setdefault("otros", []).extend(examples.pop(lab, []))
    gestures = a.gestos or [lab for lab in examples if not analysis.is_negative(lab)]
    an, dets = train(examples, noise, rate, gestures, a.modelo)
    print(f"ruido {noise:.3f} uT, {rate:.0f} Hz, ejemplos:",
          {lab: f"{inf['vistos']}/{inf['ejemplos']} vistos" for lab, inf in an["etiquetas"].items()})
    for g, d in dets.items():
        q = d.quality() if hasattr(d, "quality") else {}
        print(f"  {g}: modelo {d.chosen}  {q}")
    minutes = (rows[-1][1] - rows[0][1]) / 60
    for name, c in replay(rows, dets, windows).items():
        print(f"  activaciones de '{name}': {dict(c)}  ({c['fuera'] / minutes:.1f}/min fuera)")


if __name__ == "__main__":
    main()
