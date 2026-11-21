"""Guarda capturas de terreno y arma data/terreno_h3.parquet (ver CONTRATO.md, sección «Captura en terreno»).

- data/terreno/capturas.jsonl: una captura por línea (se puede versionar y repetir en la demo).
- data/terreno/fotos/<id>.jpg y <id>_min.jpg: foto re-codificada (sin EXIF) y miniatura. No se versionan.
- data/terreno/recorridos.jsonl: un video por línea, con su trazado GPS (posición y hora de cada punto).
- data/terreno/videos/<id>.<ext>: el video grabado. No se versiona.
- data/terreno/escuchas.jsonl: una escucha de aves por línea (posición, hora, ruido de la calle y especies que
  identificó BirdNET). Una escucha quieta son 15 s; el audio de un recorrido en video se parte en una escucha
  por hexágono recorrido (desde_s y hasta_s dentro del audio, video_id). data/terreno/audios/<archivo>.wav: el
  audio. No se versiona.

Tiempos: `tomado_en` es la hora del teléfono al tomar la foto o el cuadro; `medido_en` es la hora en que llegó
al servidor (UTC). Posición: lat, lon y precision_m del GPS del teléfono en ese momento.
- data/terreno_h3.parquet: una fila por hexágono res 9 con capturas que cuentan.

Cuentan las capturas válidas (Claude dijo que es una foto exterior de calle o espacio público). Las
descartadas nunca cuentan; las «sin validar» (sin Claude) solo si aceptar_sin_validar=True. Las escuchas
cuentan si BirdNET las analizó (BirdNET es el que valida; las «sin analizar» no suman).

Biodiversidad por hexágono (0..1) = 0,5·min(especies de aves, 5)/5 + 0,3·[se vio algún polinizador]
+ 0,2·flores (ninguna 0, pocas 0,5, muchas 1). Especies de aves: las que BirdNET oyó más las que Claude vio y
nombró (un ave vista sin nombre suma una). No detectar nada no significa que no haya fauna.
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
FLORES = {"ninguna": 0.0, "pocas": 0.5, "muchas": 1.0}
POLINIZADORES = {"abeja", "mariposa", "otro_polinizador"}
MAX_ESPECIES = 5
COLUMNAS = ["h3_index", "n_capturas", "arbol_pct_terreno", "verde_pct_terreno", "plantable",
            "viabilidad_terreno", "obstaculos", "fuente", "ultima_captura",
            "n_escuchas", "especies_aves", "n_especies_aves", "n_polinizadores", "flores", "biodiversidad_terreno"]


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
        self.audios = self.dir / "audios"
        self.audios.mkdir(parents=True, exist_ok=True)
        self.escuchas_jsonl = self.dir / "escuchas.jsonl"

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

    def escuchas(self) -> list[dict]:
        if not self.escuchas_jsonl.exists():
            return []
        with self.escuchas_jsonl.open(encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]

    def guardar_wav(self, wav: bytes, nombre: str) -> str:
        """Guarda un audio con nombre <id>.wav (p. ej. el de un recorrido) y devuelve el nombre."""
        (self.audios / f"{nombre}.wav").write_bytes(wav)
        return f"{nombre}.wav"

    def guardar_audio(self, wav: bytes | None, lat: float, lon: float, precision_m: float | None,
                      tomado_en: str | None, detecciones: list[dict] | None, duracion_s: float,
                      ruido: dict | None = None, archivo: str | None = None, extra: dict | None = None) -> dict:
        """detecciones=None: BirdNET no estaba disponible y la escucha queda «sin analizar». Con wav=None la
        escucha apunta a un audio ya guardado (archivo), p. ej. un tramo del audio de un recorrido."""
        ahora = datetime.now(timezone.utc)
        eid = f"{ahora:%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
        if wav is not None:
            archivo = self.guardar_wav(wav, eid)
        hx = h3.latlng_to_cell(lat, lon, RES)
        sin_aves_con_ruido = detecciones is not None and not detecciones and (ruido or {}).get("nivel") == "alto"
        esc = {"id": eid, "medido_en": ahora.isoformat(), "tomado_en": hora(tomado_en), "lat": lat, "lon": lon,
               "precision_m": precision_m, "duracion_s": round(duracion_s, 1), "h3_index": hx,
               "h3_padre": h3.cell_to_parent(hx, 7), "analizada": detecciones is not None,
               "detecciones": detecciones or [], "ruido": ruido, "concluyente": not sin_aves_con_ruido,
               "archivo": archivo, **(extra or {})}
        with self.escuchas_jsonl.open("a", encoding="utf-8") as f:
            f.write(json.dumps(esc, ensure_ascii=False) + "\n")
        return esc

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
        df = terreno_h3([c for c in self.capturas() if cuenta(c, self.aceptar_sin_validar)],
                        [e for e in self.escuchas() if e.get("analizada")])
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


def _media(v: list) -> float:
    v = [x for x in v if x is not None]
    return round(float(np.mean(v)), 1) if v else np.nan


def terreno_h3(capturas: list[dict], escuchas: list[dict] = ()) -> pd.DataFrame:
    """Agrega capturas y escuchas por hexágono. viabilidad_terreno es NaN si ninguna captura trae
    espacio_plantable; arbol_pct_terreno es NaN si solo hay primeros planos de fauna o flores, o solo escuchas."""
    filas = []
    por_hex: dict[str, tuple[list[dict], list[dict]]] = {}
    for c in capturas:
        por_hex.setdefault(c["h3_index"], ([], []))[0].append(c)
    for e in escuchas:
        por_hex.setdefault(e["h3_index"], ([], []))[1].append(e)
    for hx, (cs, es) in por_hex.items():
        pl = [PLANTABLE[c["espacio_plantable"]] for c in cs if c.get("espacio_plantable") in PLANTABLE]
        obst = sorted({o.strip().lower() for c in cs for o in (c.get("obstaculos") or []) if o.strip()})
        plantable = float(np.mean(pl)) if pl else np.nan
        viab = float(np.clip(plantable - CASTIGO_OBSTACULO * min(len(obst), MAX_OBSTACULOS), 0, 1)) if pl else np.nan
        fauna = [a for c in cs for a in (c.get("fauna") or [])]
        aves = {d["cientifico"] for e in es for d in e.get("detecciones", [])}
        aves |= {a["nombre"].strip().lower() for a in fauna if a.get("grupo") == "ave" and a.get("nombre", "").strip()}
        if not aves and any(a.get("grupo") == "ave" for a in fauna):
            aves = {"ave sin identificar"}
        n_pol = sum(int(a.get("cantidad", 1)) for a in fauna if a.get("grupo") in POLINIZADORES)
        fl = [FLORES[c["flores"]] for c in cs if c.get("flores") in FLORES]
        flores = max(fl) if fl else np.nan
        bio = 0.5 * min(len(aves), MAX_ESPECIES) / MAX_ESPECIES + 0.3 * (n_pol > 0) + 0.2 * (0 if np.isnan(flores) else flores)
        filas.append({
            "h3_index": hx,
            "n_capturas": len(cs),
            "arbol_pct_terreno": _media([c.get("arbol_pct", c.get("verde_pct")) for c in cs]),
            "verde_pct_terreno": _media([c.get("verde_pct") for c in cs]),
            "plantable": plantable,
            "viabilidad_terreno": viab,
            "obstaculos": "; ".join(obst),
            "fuente": "claude" if any(c.get("fuente") == "claude" for c in cs) else "indice_verde" if cs else "birdnet",
            "ultima_captura": pd.Timestamp(max(x["medido_en"] for x in cs + es)),
            "n_escuchas": len(es),
            "especies_aves": "; ".join(sorted(aves)),
            "n_especies_aves": len(aves),
            "n_polinizadores": n_pol,
            "flores": flores,
            "biodiversidad_terreno": round(float(bio), 3),
        })
    df = pd.DataFrame(filas, columns=COLUMNAS)
    return df.astype({"h3_index": "str", "n_capturas": "int64", "arbol_pct_terreno": "float64",
                      "verde_pct_terreno": "float64", "plantable": "float64", "viabilidad_terreno": "float64",
                      "obstaculos": "str", "fuente": "str", "n_escuchas": "int64", "especies_aves": "str",
                      "n_especies_aves": "int64", "n_polinizadores": "int64", "flores": "float64",
                      "biodiversidad_terreno": "float64"})
