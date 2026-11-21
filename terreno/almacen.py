"""Guarda capturas de terreno y arma data/terreno_h3.parquet (ver CONTRATO.md, sección «Captura en terreno»).

- data/terreno/capturas.jsonl: una captura por línea (se puede versionar y repetir en la demo).
- data/terreno/fotos/<id>.jpg y <id>_min.jpg: foto re-codificada (sin EXIF) y miniatura. No se versionan.
- data/terreno/recorridos.jsonl: un video por línea, con su trazado GPS (posición y hora de cada punto).
- data/terreno/videos/<id>.<ext>: el video grabado. No se versiona.

Tiempos: `tomado_en` es la hora del teléfono al tomar la foto o el cuadro; `medido_en` es la hora en que llegó
al servidor (UTC). Posición: lat, lon y precision_m del GPS del teléfono en ese momento.
- data/terreno_h3.parquet: una fila por hexágono res 9 con capturas que cuentan.

Cuentan las capturas válidas (Claude dijo que es una foto exterior de calle o espacio público). Las
descartadas nunca cuentan; las «sin validar» (sin Claude) solo si aceptar_sin_validar=True.
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


def estado_validacion(c: dict) -> str:
    v = c.get("valida")
    return "valida" if v is True else "descartada" if v is False else "sin_validar"


def cuenta(c: dict, aceptar_sin_validar: bool = False) -> bool:
    e = estado_validacion(c)
    return e == "valida" or (e == "sin_validar" and aceptar_sin_validar)


class Almacen:
    def __init__(self, data: Path = Path("data"), aceptar_sin_validar: bool = False):
        self.data = Path(data)
        self.aceptar_sin_validar = aceptar_sin_validar
        self.dir = self.data / "terreno"
        self.fotos = self.dir / "fotos"
        self.jsonl = self.dir / "capturas.jsonl"
        self.videos = self.dir / "videos"
        self.recorridos_jsonl = self.dir / "recorridos.jsonl"
        self.videos.mkdir(parents=True, exist_ok=True)
        self.parquet = self.data / "terreno_h3.parquet"
        self.fotos.mkdir(parents=True, exist_ok=True)

    def capturas(self) -> list[dict]:
        if not self.jsonl.exists():
            return []
        with self.jsonl.open(encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]

    def recorridos(self) -> list[dict]:
        if not self.recorridos_jsonl.exists():
            return []
        with self.recorridos_jsonl.open(encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]

    def guardar_video(self, video: bytes | None, ext: str, inicio: str | None, track: list[dict],
                      n_cuadros: int, nota: str = "") -> dict:
        ahora = datetime.now(timezone.utc)
        vid = f"{ahora:%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
        archivo = None
        if video:
            archivo = f"{vid}.{ext}"
            (self.videos / archivo).write_bytes(video)
        t = [p.get("t_s", 0) for p in track]
        rec = {"id": vid, "medido_en": ahora.isoformat(), "inicio": hora(inicio), "archivo": archivo,
               "duracion_s": round(max(t) - min(t), 1) if t else 0, "n_cuadros": n_cuadros,
               "nota": nota[:200], "track": track}
        with self.recorridos_jsonl.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec

    def guardar(self, foto: bytes, lat: float, lon: float, precision_m: float | None = None,
                rumbo: float | None = None, nota: str = "", obs: dict | None = None,
                tomado_en: str | None = None, extra: dict | None = None) -> dict:
        ahora = datetime.now(timezone.utc)
        cid = f"{ahora:%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(foto))).convert("RGB")  # sin EXIF al guardar
        img.thumbnail((1280, 1280))
        img.save(self.fotos / f"{cid}.jpg", "JPEG", quality=85)
        img.thumbnail((320, 320))
        img.save(self.fotos / f"{cid}_min.jpg", "JPEG", quality=80)
        hx = h3.latlng_to_cell(lat, lon, RES)
        cap = {"id": cid, "medido_en": ahora.isoformat(), "tomado_en": hora(tomado_en), "lat": lat, "lon": lon,
               "precision_m": precision_m, "rumbo": rumbo, "nota": nota[:200],
               "h3_index": hx, "h3_padre": h3.cell_to_parent(hx, 7), **(extra or {}), **(obs or {})}
        with self.jsonl.open("a", encoding="utf-8") as f:
            f.write(json.dumps(cap, ensure_ascii=False) + "\n")
        return cap

    def escribir_h3(self) -> pd.DataFrame:
        df = terreno_h3([c for c in self.capturas() if cuenta(c, self.aceptar_sin_validar)])
        df.to_parquet(self.parquet, index=False)
        return df


def hora(texto: str | None) -> str | None:
    """Hora ISO 8601 del teléfono normalizada a UTC, o None si no viene o no se entiende."""
    if not texto:
        return None
    try:
        t = datetime.fromisoformat(str(texto).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat()


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
