"""Guarda capturas de terreno y arma data/terreno_h3.parquet (ver CONTRATO.md, sección «Captura en terreno»).

- data/terreno/capturas.jsonl: una captura por línea (se puede versionar y repetir en la demo).
- data/terreno/fotos/<id>.jpg y <id>_min.jpg: foto re-codificada (sin EXIF) y miniatura. No se versionan.
- data/terreno_h3.parquet: una fila por hexágono res 9 con capturas.
"""
from __future__ import annotations

import io
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import h3
import numpy as np
import pandas as pd
from PIL import Image, ImageOps

RES = 9
PLANTABLE = {"ninguno": 0.0, "poco": 0.33, "medio": 0.67, "mucho": 1.0}
CASTIGO_OBSTACULO = 0.15
MAX_OBSTACULOS = 3
COLUMNAS = ["h3_index", "n_capturas", "arbol_pct_terreno", "verde_pct_terreno", "plantable",
            "viabilidad_terreno", "obstaculos", "fuente", "ultima_captura"]


class Almacen:
    def __init__(self, data: Path = Path("data")):
        self.data = Path(data)
        self.dir = self.data / "terreno"
        self.fotos = self.dir / "fotos"
        self.jsonl = self.dir / "capturas.jsonl"
        self.parquet = self.data / "terreno_h3.parquet"
        self.fotos.mkdir(parents=True, exist_ok=True)

    def capturas(self) -> list[dict]:
        if not self.jsonl.exists():
            return []
        with self.jsonl.open(encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]

    def guardar(self, foto: bytes, lat: float, lon: float, precision_m: float | None = None,
                rumbo: float | None = None, nota: str = "", obs: dict | None = None) -> dict:
        ahora = datetime.now(timezone.utc)
        cid = f"{ahora:%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(foto))).convert("RGB")  # sin EXIF al guardar
        img.thumbnail((1280, 1280))
        img.save(self.fotos / f"{cid}.jpg", "JPEG", quality=85)
        img.thumbnail((320, 320))
        img.save(self.fotos / f"{cid}_min.jpg", "JPEG", quality=80)
        hx = h3.latlng_to_cell(lat, lon, RES)
        cap = {"id": cid, "medido_en": ahora.isoformat(), "lat": lat, "lon": lon,
               "precision_m": precision_m, "rumbo": rumbo, "nota": nota[:200],
               "h3_index": hx, "h3_padre": h3.cell_to_parent(hx, 7), **(obs or {})}
        with self.jsonl.open("a", encoding="utf-8") as f:
            f.write(json.dumps(cap, ensure_ascii=False) + "\n")
        return cap

    def escribir_h3(self) -> pd.DataFrame:
        df = terreno_h3(self.capturas())
        df.to_parquet(self.parquet, index=False)
        return df


def terreno_h3(capturas: list[dict]) -> pd.DataFrame:
    """Agrega capturas por hexágono. viabilidad_terreno es NaN si ninguna captura trae espacio_plantable."""
    filas = []
    por_hex: dict[str, list[dict]] = {}
    for c in capturas:
        por_hex.setdefault(c["h3_index"], []).append(c)
    for hx, cs in por_hex.items():
        pl = [PLANTABLE[c["espacio_plantable"]] for c in cs if c.get("espacio_plantable") in PLANTABLE]
        obst = sorted({o.strip().lower() for c in cs for o in (c.get("obstaculos") or []) if o.strip()})
        plantable = float(np.mean(pl)) if pl else np.nan
        viab = float(np.clip(plantable - CASTIGO_OBSTACULO * min(len(obst), MAX_OBSTACULOS), 0, 1)) if pl else np.nan
        filas.append({
            "h3_index": hx,
            "n_capturas": len(cs),
            "arbol_pct_terreno": round(float(np.mean([c.get("arbol_pct", c.get("verde_pct", 0)) for c in cs])), 1),
            "verde_pct_terreno": round(float(np.mean([c.get("verde_pct", 0) for c in cs])), 1),
            "plantable": plantable,
            "viabilidad_terreno": viab,
            "obstaculos": "; ".join(obst),
            "fuente": "claude" if any(c.get("fuente") == "claude" for c in cs) else "indice_verde",
            "ultima_captura": pd.Timestamp(max(c["medido_en"] for c in cs)),
        })
    df = pd.DataFrame(filas, columns=COLUMNAS)
    return df.astype({"h3_index": "str", "n_capturas": "int64", "arbol_pct_terreno": "float64",
                      "verde_pct_terreno": "float64", "plantable": "float64", "viabilidad_terreno": "float64",
                      "obstaculos": "str", "fuente": "str"})
