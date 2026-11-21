"""Análisis de una foto de calle tomada en terreno.

Dos capas:
- indice_verde: siempre corre, sin red. Índice de exceso de verde (ExG = 2g − r − b, con rgb normalizado)
  sobre la foto reducida; verde_pct = % de píxeles con vegetación.
- analizar_claude: si hay credenciales de Anthropic, Claude estima coberturas, espacio plantable y
  obstáculos. Si falla (sin credenciales, red, rechazo), se sigue solo con el índice.

Son estimaciones de una vista a nivel de calle: complementan al satélite, no lo reemplazan.
"""
from __future__ import annotations

import base64
import io
import logging
from typing import Literal

import numpy as np
from PIL import Image, ImageOps
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

MODELO = "claude-opus-5-5"
UMBRAL_EXG = 0.08   # píxel con vegetación si 2g − r − b > umbral (rgb normalizado a suma 1)
LADO_INDICE = 256

PROMPT = """Eres un apoyo para planificar corredores verdes en Santiago de Chile.
La foto fue tomada a nivel de calle por un equipo en terreno. Estima, para lo que se ve en la foto:
- porcentaje de la vista cubierto por árboles, arbustos, pasto, suelo desnudo, construcciones y pavimento
  (los seis deberían sumar cerca de 100);
- cuánto espacio hay para plantar árboles o arbustos nuevos (veredas anchas, bandejones, sitios eriazos,
  platabandas sin árboles): ninguno, poco, medio o mucho;
- obstáculos concretos para plantar (cables aéreos, vereda angosta, entradas de autos, ductos, etc.).
Si la foto no muestra una calle o un espacio exterior, responde espacio_plantable "ninguno" y explícalo
en la descripción. Sé conservador: no inventes lo que no se ve."""


class Observacion(BaseModel):
    arbol_pct: float = Field(ge=0, le=100)
    arbusto_pct: float = Field(ge=0, le=100)
    pasto_pct: float = Field(ge=0, le=100)
    suelo_desnudo_pct: float = Field(ge=0, le=100)
    construido_pct: float = Field(ge=0, le=100)
    pavimento_pct: float = Field(ge=0, le=100)
    espacio_plantable: Literal["ninguno", "poco", "medio", "mucho"]
    obstaculos: list[str]
    descripcion: str


def _abrir(jpeg: bytes) -> Image.Image:
    return ImageOps.exif_transpose(Image.open(io.BytesIO(jpeg))).convert("RGB")


def indice_verde(jpeg: bytes) -> dict:
    img = _abrir(jpeg)
    img.thumbnail((LADO_INDICE, LADO_INDICE))
    a = np.asarray(img, dtype=np.float64)
    s = a.sum(axis=2)
    s[s == 0] = 1
    r, g, b = (a[..., i] / s for i in range(3))
    exg = 2 * g - r - b
    return {"verde_pct": round(float((exg > UMBRAL_EXG).mean() * 100), 1)}


_sin_credenciales = False  # se marca tras el primer intento sin credenciales, para no reintentar en cada foto


def _cliente():
    """Cliente de Anthropic (credenciales: ANTHROPIC_API_KEY, token o perfil de `ant`), o None."""
    if _sin_credenciales:
        return None
    try:
        import anthropic
        return anthropic.Anthropic(timeout=30.0, max_retries=1)
    except Exception as e:  # sin paquete o configuración inválida: modo offline
        log.info("Claude no disponible (%s); solo índice de verde", e)
        return None


def analizar_claude(jpeg: bytes, cliente=None) -> Observacion | None:
    import anthropic

    c = cliente or _cliente()
    if c is None:
        return None
    img = _abrir(jpeg)
    img.thumbnail((1280, 1280))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    datos = base64.standard_b64encode(buf.getvalue()).decode()
    try:
        r = c.beta.messages.parse(
            model=MODELO,
            max_tokens=4000,
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_format=Observacion,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": datos}},
                {"type": "text", "text": PROMPT},
            ]}],
        )
    except anthropic.AuthenticationError:
        log.warning("Credenciales de Anthropic inválidas; solo índice de verde")
        return None
    except anthropic.RateLimitError:
        log.warning("Límite de Anthropic; solo índice de verde")
        return None
    except anthropic.APIStatusError as e:
        log.warning("Error %s de Anthropic; solo índice de verde", e.status_code)
        return None
    except anthropic.APIConnectionError:
        log.warning("Sin conexión con Anthropic; solo índice de verde")
        return None
    except Exception as e:  # p. ej. salida que no valida contra el esquema
        if "authentication method" in str(e):  # el SDK no encontró credenciales: no reintentar
            global _sin_credenciales
            _sin_credenciales = True
            log.info("Sin credenciales de Anthropic; solo índice de verde")
        else:
            log.warning("Análisis con Claude falló (%s); solo índice de verde", e)
        return None
    if r.stop_reason == "refusal" or r.parsed_output is None:
        return None
    return r.parsed_output


def analizar(jpeg: bytes, usar_claude: bool = True) -> dict:
    """Une el índice (siempre) con Claude (si está). Devuelve un dict plano listo para guardar."""
    out = indice_verde(jpeg)
    obs = analizar_claude(jpeg) if usar_claude else None
    if obs is not None:
        out.update(obs.model_dump(), fuente="claude")
    else:
        out.update(arbol_pct=out["verde_pct"], espacio_plantable=None, obstaculos=[],
                   descripcion="Solo índice de verde (sin análisis de Claude).", fuente="indice_verde")
    return out
