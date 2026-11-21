"""Mide los aciertos de los detectores sobre grabaciones reales (data/session_*.csv).

Las grabaciones necesitan la columna "label": se llena desde el panel con el
boton "Grabar ejemplo" mientras haces el gesto/estado.

Ejemplos:
  # Gesto puntual: aprende la direccion con los 3 primeros "contraccion" y mide el resto
  python evaluate.py data/session_X.csv --event contraccion

  # Estados: cada etiqueta es un estado (p. ej. "abierta" y "cerrada")
  python evaluate.py data/session_X.csv --state --labels abierta cerrada

  # Ritmo: tramos "respira" con 12 respiraciones/min contadas a mano, y tramos "pausa"
  python evaluate.py data/session_X.csv --rhythm respira --per-min 12 --band 0.1 0.7
"""

from __future__ import annotations

import argparse
import csv
import sys

import numpy as np

from detectors import (Bank, DirectionModel, EventDetector, RhythmDetector,
                       StateDetector, deltas_for, segments)


def load(path):
    """Lee un CSV del servidor. Devuelve t, xyz, labels y gyro [(t, wx, wy, wz)]."""
    t, xyz, labels, gyro = [], [], [], []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            if not row.get("x") and row.get("gx"):
                try:
                    gyro.append((float(row["t"]), float(row["gx"]), float(row["gy"]), float(row["gz"])))
                except ValueError:
                    pass
                continue
            try:
                t.append(float(row["t"]))
                xyz.append((float(row["x"]), float(row["y"]), float(row["z"])))
            except (KeyError, ValueError):
                continue
            labels.append((row.get("label") or "").strip())
    if not t:
        sys.exit(f"{path}: sin lecturas")
    return np.array(t), np.array(xyz), labels, gyro


GYRO: list = []      # lecturas del giroscopio del archivo actual (si las hay)


def replay(bank, t, xyz):
    """Pasa las lecturas por el banco, intercalando el giroscopio por tiempo."""
    events, gi = [], 0
    g = [x for x in GYRO if t[0] - 1 <= x[0] <= t[-1]] if len(t) else []
    for ti, v in zip(t, xyz):
        while gi < len(g) and g[gi][0] <= ti:
            bank.gyro(g[gi][0], g[gi][1:])
            gi += 1
        events.extend(bank.step(ti, v))
    return events


def eval_event(t, xyz, labels, target, n_train=3, **kw):
    segs = [s for s in segments(labels) if s[2] == target]
    if len(segs) < n_train + 1:
        sys.exit(f"Hay {len(segs)} ejemplos '{target}'. Necesito al menos {n_train + 1} "
                 f"({n_train} para aprender y el resto para medir).")
    train, test = segs[:n_train], segs[n_train:]
    direction = DirectionModel.fit([deltas_for(xyz, t, s) for s in train])
    cons = direction.consistency([deltas_for(xyz, t, s) for s in train])

    results = {}
    for name, d in [("con direccion", direction), ("solo magnitud (fase 1)", None)]:
        bank = Bank()
        bank.add(EventDetector(target, direction=d, **kw))
        starts = [e for e in replay(bank, t, xyz) if e["kind"] == "start"]
        train_spans = [(t[a] - 0.3, t[b - 1] + 1.0) for a, b, _ in train]
        starts = [e for e in starts if not any(lo <= e["t"] <= hi for lo, hi in train_spans)]
        hits, lat, used = 0, [], set()
        for a, b, _ in test:
            lo, hi = t[a] - 0.3, t[b - 1] + 1.0
            m = [i for i, e in enumerate(starts) if lo <= e["t"] <= hi and i not in used]
            if m:
                hits += 1
                used.add(m[0])
                lat.append(starts[m[0]]["t"] - t[a])
        fp = len(starts) - len(used)
        results[name] = (hits, len(test), fp, lat)

    print(f"\nEvento '{target}': {len(train)} ejemplos para aprender, {len(test)} para medir")
    print(f"  Direccion aprendida u={np.round(direction.u, 3).tolist()}, pico tipico "
          f"{direction.peak:.2f} uT, parecido entre ejemplos (coseno min) {cons:.2f}")
    for name, (h, n, fp, lat) in results.items():
        rec = h / n if n else 0
        prec = h / (h + fp) if h + fp else 0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0
        ml = f"{1000 * np.median(lat):.0f} ms" if lat else "-"
        print(f"  {name:24s} aciertos {h}/{n} ({rec:.0%})  falsas alarmas {fp}  "
              f"precision {prec:.0%}  F1 {f1:.2f}  latencia mediana {ml}")
    return results


def eval_state(t, xyz, labels, train_frac=0.4, only=None):
    segs = [s for s in segments(labels) if not only or s[2] in only]
    names = sorted({s[2] for s in segs})
    if len(names) < 2:
        sys.exit("Necesito al menos dos estados con etiquetas distintas.")
    # Suavizar igual que en vivo
    bank = Bank()
    smooth = []
    for ti, v in zip(t, xyz):
        s, _, _ = bank.pipeline.step(ti, v)
        smooth.append(s.copy())
    smooth = np.array(smooth)

    train, test_idx = {}, []
    for a, b, lab in segs:
        cut = a + max(1, int((b - a) * train_frac))
        train.setdefault(lab, []).append(smooth[a:cut])
        test_idx.extend((i, lab) for i in range(cut, b))
    det = StateDetector("estado").fit(train)
    ok = sum(det.classify(smooth[i]) == lab for i, lab in test_idx)
    unknown = sum(det.classify(smooth[i]) is None for i, _ in test_idx)
    print(f"\nEstados {names}: aprende con el primer {train_frac:.0%} de cada tramo")
    print(f"  Separacion entre estados {det.separation():.1f} (mas de 2 es bueno)")
    print(f"  Aciertos por muestra {ok}/{len(test_idx)} ({ok / max(len(test_idx), 1):.0%}), "
          f"sin decidir {unknown}")
    conf = {a: {b: 0 for b in names + [None]} for a in names}
    for i, lab in test_idx:
        conf[lab][det.classify(smooth[i])] += 1
    print("  Matriz (fila = real, columna = detectado):")
    print("   " + "".join(f"{str(n):>12s}" for n in names + ["?"]))
    for a in names:
        print(f"   {a:>10s}" + "".join(f"{conf[a][b]:>12d}" for b in names + [None]))
    return ok, len(test_idx)


def eval_rhythm(t, xyz, labels, target, band, per_min=None, pause_label="pausa", pause_s=10.0):
    segs = segments(labels)
    rhy = [s for s in segs if s[2] == target]
    pauses = [s for s in segs if s[2] == pause_label]
    if not rhy:
        sys.exit(f"No hay tramos '{target}'.")
    print(f"\nRitmo '{target}' en banda {band[0]}-{band[1]} Hz")
    for a, b, _ in rhy:
        bank = Bank()
        bank.pipeline.baseline = xyz[max(a - 50, 0):a + 1].mean(axis=0)  # sin calibrar
        det = RhythmDetector(target, band=tuple(band), window=min(20.0, t[b - 1] - t[a]))
        bank.add(det)
        replay(bank, t[a:b], xyz[a:b])
        est = det.freq * 60 if det.freq else None
        ref = f", referencia {per_min}/min, error {abs(est - per_min):.1f}/min" if per_min and est else ""
        print(f"  tramo {t[a] - t[0]:6.1f}-{t[b - 1] - t[0]:6.1f} s: "
              f"{est:.1f}/min" if est else "  sin ritmo detectado", end="")
        print(f", amplitud {det.amp:.2f} uT{ref}")
    if pauses:
        bank = Bank()
        det = RhythmDetector(target, band=tuple(band), pause_s=pause_s)
        bank.add(det)
        ev = replay(bank, t, xyz)
        pev = [e for e in ev if e["kind"] == "pause"]
        hit = sum(any(t[a] <= e["t"] <= t[b - 1] + pause_s for e in pev) for a, b, _ in pauses)
        print(f"  Pausas avisadas {hit}/{len(pauses)}, avisos totales {len(pev)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="+")
    ap.add_argument("--event", metavar="ETIQUETA")
    ap.add_argument("--state", action="store_true")
    ap.add_argument("--labels", nargs="+", help="con --state: solo estas etiquetas")
    ap.add_argument("--rhythm", metavar="ETIQUETA")
    ap.add_argument("--band", nargs=2, type=float, default=[0.1, 0.7])
    ap.add_argument("--per-min", type=float)
    ap.add_argument("--train", type=int, default=3)
    ap.add_argument("--min-on-ms", type=float, default=150)
    a = ap.parse_args()
    for path in a.csv:
        t, xyz, labels, gyro = load(path)
        GYRO[:] = gyro
        print(f"== {path}: {len(t)} lecturas, giroscopio {'si' if gyro else 'no'}, {t[-1] - t[0]:.1f} s, "
              f"{(len(t) - 1) / max(t[-1] - t[0], 1e-9):.0f} Hz")
        if a.event:
            eval_event(t, xyz, labels, a.event, a.train, min_on=a.min_on_ms / 1000)
        if a.state:
            eval_state(t, xyz, labels, only=a.labels)
        if a.rhythm:
            eval_rhythm(t, xyz, labels, a.rhythm, a.band, a.per_min)
        if not (a.event or a.state or a.rhythm):
            segs = segments(labels)
            print("  Etiquetas:", {lab: sum(1 for s in segs if s[2] == lab) for lab in {s[2] for s in segs}})


if __name__ == "__main__":
    main()
