"""Fondo del titular: Sentinel-2 del Gran Santiago con la vegetación realzada y lo construido en gris.

Pasada del 2026-02-06 (teselas T19HCD y T19HCC, verano sin nubes), 16 m por píxel, vía Planetary
Computer. Color real estirado; NDVI decide la mezcla entre un gris cálido (lo construido, según su
brillo) y los verdes de la paleta (la vegetación, según su NDVI). Sin texto. Correr con el entorno de
verdeh3 (corredores-verdes):
    python web/scripts/fondo_satelital.py --verdeh3 ../corredores-verdes
Escribe web/public/img/santiago-s2.webp (2400 px) y santiago-s2-1200.webp.
"""
import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

WEB = Path(__file__).resolve().parents[1]
BBOX = (-70.86, -33.66, -70.43, -33.30)


def bajar(fecha="2026-02-06", res=16):
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.merge import merge
    from rasterio.warp import transform_bounds
    from verdeh3 import mosaico_s2

    its = mosaico_s2.teselas_de_una_pasada(BBOX, fecha)
    out = {}
    for banda in ["B02", "B03", "B04", "B08"]:
        fs = [rasterio.open(i.assets[banda].href) for i in its]
        b = transform_bounds("EPSG:4326", fs[0].crs, *BBOX)
        out[banda] = merge(fs, bounds=b, res=res, nodata=0, resampling=Resampling.average)[0][0]
    base = min(str(i.properties.get("s2:processing_baseline", "04.00")) for i in its)
    return out, 1000 if base >= "04.00" else 0


def pintar(d, off):
    r, g, b, n = [(d[k].astype("float32") - off) / 1e4 for k in ("B04", "B03", "B02", "B08")]
    valido = d["B04"] > 0
    ndvi = np.where(valido, (n - r) / np.maximum(n + r, 1e-4), 0)
    def estira(x, lo=2, hi=98):
        a, z = np.percentile(x[valido], [lo, hi]); return np.clip((x - a) / (z - a), 0, 1)
    rgb = np.stack([estira(r), estira(g), estira(b)], -1) ** (1 / 1.25)
    lum = rgb @ np.array([0.3, 0.59, 0.11], "float32")
    # Construido: gris cálido, de piedra oscura a crema
    gris = np.array([0x5E, 0x5A, 0x50], "float32") / 255; crema = np.array([0xEC, 0xE6, 0xD6], "float32") / 255
    t = np.clip(lum, 0, 1)[..., None] ** 0.9
    urbano = gris + (crema - gris) * t
    # Vegetación: verdes de la paleta según NDVI, con algo de textura real
    v = np.clip((ndvi - 0.2) / 0.45, 0, 1)[..., None]
    salvia = np.array([0x86, 0xA0, 0x48], "float32") / 255; bosque = np.array([0x2C, 0x4A, 0x1C], "float32") / 255
    verde = (salvia + (bosque - salvia) * v) * (0.75 + 0.5 * lum[..., None])
    w = np.clip((ndvi - 0.17) / 0.18, 0, 1)[..., None]; w = w * w * (3 - 2 * w)
    img = np.clip(urbano * (1 - w) + verde * w, 0, 1)
    img[~valido] = crema
    im = Image.fromarray((img * 255).astype("uint8"))
    return im


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verdeh3", type=Path, required=True, help="carpeta que contiene el paquete verdeh3")
    sys.path.insert(0, str(ap.parse_args().verdeh3.resolve()))
    im = pintar(*bajar())
    W, H = im.size
    h = int(W * 9 / 16)
    y0 = int((H - h) * 0.45)
    hero = im.crop((0, y0, W, y0 + h)).resize((2400, 1350), Image.LANCZOS)
    hero.save(WEB / "public/img/santiago-s2.webp", quality=80, method=6)
    hero.resize((1200, 675), Image.LANCZOS).save(WEB / "public/img/santiago-s2-1200.webp", quality=78, method=6)


if __name__ == "__main__":
    main()
