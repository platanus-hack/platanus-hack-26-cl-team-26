"""Exporta los datos reales de data/ a JSON estático para la página web (web/public/data/).

Correr desde la raíz del repo, con el mismo entorno de optimizer.py:
    python web/scripts/exportar_datos.py

Escribe:
  hexes.json      una fila por hexágono de las comunas piloto (santiago_h3.parquet)
  vivo.json       barrios con aire en vivo (live_h3.parquet) y sensores (web_sensors.json)
  historico.json  lst_c por hexágono y mes, 2023-01 a 2026-11 (historico_h3.parquet)
  cifras.json     cifras_pitch.json y el corredor de referencia de solve_corridor (40/40/20, 3 km)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
from optimizer import solve_corridor  # noqa: E402

DATA = RAIZ / "data"
SALIDA = RAIZ / "web" / "public" / "data"


def _r(x, d=2):
    return None if x is None or pd.isna(x) else round(float(x), d)


def main():
    SALIDA.mkdir(parents=True, exist_ok=True)
    df = pd.read_parquet(DATA / "santiago_h3.parquet")
    live = pd.read_parquet(DATA / "live_h3.parquet") if (DATA / "live_h3.parquet").exists() else None
    ref = solve_corridor(df, budget_km=3.0, live=live)

    hexes = [
        {
            "h": r.h3_index, "p": r.h3_padre, "c": r.comuna,
            "t": _r(r.lst_c, 4), "tu": _r(r.lst_c_ultima), "v": _r(r.ndvi, 3),
            "a": _r(r.copa_modelo_pct, 3), "n": int(r.poblacion), "s": _r(r.social, 4),
            "k": bool(r.es_parque), "u": _r(u, 5),
        }
        for r, u in zip(df.itertuples(), ref["urgencia"])
    ]
    (SALIDA / "hexes.json").write_text(json.dumps(hexes, ensure_ascii=False, separators=(",", ":")))

    vivo = {"barrios": [], "sensores": []}
    if live is not None:
        for r in live.itertuples():
            vivo["barrios"].append({
                "p": r.h3_padre, "t": _r(r.temp_aire_c), "conf": r.confianza,
                "medido": None if pd.isna(r.medido_en) else str(r.medido_en),
            })
    if (DATA / "web_sensors.json").exists():
        vivo["sensores"] = json.loads((DATA / "web_sensors.json").read_text())
    (SALIDA / "vivo.json").write_text(json.dumps(vivo, ensure_ascii=False, separators=(",", ":")))

    hist = pd.read_parquet(DATA / "historico_h3.parquet", columns=["mes", "h3_index", "lst_c"])
    hist = hist[hist["h3_index"].isin(df["h3_index"])]
    meses = sorted(hist["mes"].unique())
    tabla = hist.groupby(["h3_index", "mes"])["lst_c"].mean().unstack("mes").reindex(columns=meses)
    meta = json.loads((DATA / "historico_meta.json").read_text())
    (SALIDA / "historico.json").write_text(json.dumps({
        "meses": meses,
        "escenas_landsat": meta["escenas_landsat"], "escenas_sentinel2": meta["escenas_sentinel2"],
        "lst": {h: [_r(x, 1) for x in fila] for h, fila in zip(tabla.index, tabla.to_numpy())},
    }, separators=(",", ":")))

    cifras = json.loads((DATA / "cifras_pitch.json").read_text())
    cifras["lst_fecha"] = str(df["lst_fecha"].mode().iloc[0])
    cifras["lst_fecha_ultima"] = str(df["lst_fecha_ultima"].mode().iloc[0])
    cifras["referencia"] = {k: ref[k] for k in ("hexes", "length_km", "urgencia_cubierta", "urgencia_azar",
                                                "personas_cubiertas", "personas_azar", "tramos")}
    (SALIDA / "cifras.json").write_text(json.dumps(cifras, ensure_ascii=False, indent=1))
    print(f"{len(hexes)} hexágonos, {len(meses)} meses, corredor {ref['personas_cubiertas']} vs {ref['personas_azar']}")


if __name__ == "__main__":
    main()
