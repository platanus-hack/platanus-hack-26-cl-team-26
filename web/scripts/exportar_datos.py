"""Exporta la serie mensual del Gran Santiago para las barras del histórico (web/public/data/historico.json).

El mapa y las cifras de la página vienen en vivo del servidor de terreno (terreno/servidor.py); esto es
lo único estático. Correr desde la raíz del repo:
    python web/scripts/exportar_datos.py                     # usa data/ de este repo
    python web/scripts/exportar_datos.py --fuente ../ayuda   # o la de otra copia
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

WEB = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fuente", type=Path, default=WEB.parent, help="raíz con data/")
    data = ap.parse_args().fuente.resolve() / "data"
    df = pd.read_parquet(data / "santiago_h3_gs.parquet", columns=["h3_index", "lst_fecha_ultima"])
    hist = pd.read_parquet(data / "historico_h3.parquet", columns=["mes", "h3_index", "lst_c"])
    hist = hist[hist["h3_index"].isin(df["h3_index"])]
    por_mes = hist.groupby("mes")["lst_c"].mean()
    meta = json.loads((data / "historico_meta.json").read_text(encoding="utf-8"))
    meses = sorted(hist["mes"].unique())
    salida = WEB / "public" / "data" / "historico.json"
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(json.dumps({
        "meses": meses, "escenas_landsat": meta["escenas_landsat"], "escenas_sentinel2": meta["escenas_sentinel2"],
        "media_mes": [None if pd.isna(por_mes.get(m)) else round(float(por_mes[m]), 2) for m in meses],
        "lst_fecha_ultima": str(df["lst_fecha_ultima"].mode().iloc[0]),
    }, separators=(",", ":")), encoding="utf-8")
    print(f"{len(meses)} meses -> {salida}")


if __name__ == "__main__":
    main()
