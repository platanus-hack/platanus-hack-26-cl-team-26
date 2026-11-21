"""Repite una grabacion por el detector del servidor y lista las activaciones.

Sirve para medir antes y despues de un cambio sobre datos reales:
  python replay.py data/session_X.csv
Marca como "sospechosa" una activacion cuyo cambio real de campo (|d|) es
menor que --min-change uT: esas son las que se disparan solas.
"""
import argparse
import csv
import os

os.environ.setdefault("VOICE", "0")
import numpy as np  # noqa: E402

import server  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--min-change", type=float, default=5.0)
    a = ap.parse_args()
    det, bank = server.Detector(), server.Bank()
    p = bank.pipeline
    rows, ons, drifts = [], [], 0
    with open(a.csv, newline="") as f:
        for r in csv.DictReader(f):
            t = float(r["t"])
            if not r.get("x"):
                if r.get("gx"):
                    bank.gyro(t, (float(r["gx"]), float(r["gy"]), float(r["gz"])))
                continue
            v = np.array([float(r["x"]), float(r["y"]), float(r["z"])])
            bank.step(t, v)
            moving = p.phone_moving(t)
            vr = p.R @ v
            ev = det.process(t, *map(float, vr), allow=not moving)
            rows.append((t, v))
            if "on" in ev:
                ons.append(len(rows) - 1)
            drifts += "drift" in ev
    T = np.array([r[0] for r in rows])
    X = np.array([r[1] for r in rows])
    sus = 0
    print(f"{a.csv}: {len(T)} lecturas, {T[-1] - T[0]:.0f} s")
    for i in ons:
        pre = X[max(i - 100, 0):max(i - 20, 1)].mean(axis=0)
        win = X[i:i + 60]
        d = float(np.linalg.norm(win - pre, axis=1).max())
        flag = d < a.min_change
        sus += flag
        print(f"  {T[i] - T[0]:8.1f} s  |d|={d:6.1f} uT {'SOSPECHOSA' if flag else ''}")
    print(f"activaciones {len(ons)}, sospechosas (|d|<{a.min_change:g} uT) {sus}, derivas absorbidas {drifts}")


if __name__ == "__main__":
    main()
