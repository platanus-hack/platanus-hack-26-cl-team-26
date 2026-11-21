"""Análisis de una foto de calle tomada en terreno.

Dos capas:
- indice_verde: siempre corre, sin red. Índice de exceso de verde (ExG = 2g − r − b, con rgb normalizado)
  sobre la foto reducida; verde_pct = % de píxeles con vegetación.
- analizar_claude: si hay credenciales de Anthropic, Claude primero decide si la foto sirve (exterior, calle o
  espacio público, a nivel de suelo) y luego estima coberturas, espacio plantable y obstáculos.
  Si falla (sin credenciales, red, rechazo), se sigue solo con el índice.

Validez: el índice de verde no distingue una oficina de una calle, así que sin Claude la captura queda
«sin validar» (valida=None) y no cambia el corredor salvo que el servidor lo permita (--aceptar-sin-validar).

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
Un equipo en terreno debería tomar esta foto a nivel de calle para verificar una cuadra.

Primero decide si la foto sirve (valida):
- valida = true solo si es una foto exterior de una calle, vereda, plaza, bandejón, sitio eriazo u otro
  espacio público, tomada a nivel de suelo.
- valida = false si es un interior (oficina, casa, local), una vista a través de una ventana o desde un piso
  alto, una pantalla o un documento, un primer plano de personas u objetos, o si está tan oscura o borrosa que
  no se distingue el entorno. En ese caso explica el motivo en una frase corta y deja los porcentajes en 0,
  espacio_plantable "ninguno" y obstaculos vacío.

Si es válida, estima para lo que se ve en la foto:
- porcentaje de la vista cubierto por árboles, arbustos, pasto, suelo desnudo, construcciones y pavimento
  (los seis deberían sumar cerca de 100);
- cuánto espacio hay para plantar árboles o arbustos nuevos (veredas anchas, bandejones, sitios eriazos,
  platabandas sin árboles): ninguno, poco, medio o mucho;
- obstáculos concretos para plantar (cables aéreos, vereda angosta, entradas de autos, ductos, etc.).
Sé conservador: no inventes lo que no se ve. No describas a las personas que aparezcan."""


class Observacion(BaseModel):
    valida: bool
    motivo_rechazo: str
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
        if not obs.valida:
            out.update(espacio_plantable=None, obstaculos=[])
    else:
        out.update(arbol_pct=out["verde_pct"], espacio_plantable=None, obstaculos=[], valida=None,
                   motivo_rechazo="", fuente="indice_verde",
                   descripcion="Sin validar: solo índice de verde, que no distingue una calle de un interior.")
    return out
