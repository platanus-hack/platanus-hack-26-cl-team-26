"""NDVI de Sentinel-2 para áreas que ninguna tesela cubre sola (p. ej. el Gran Santiago).

python -m verdeh3.mosaico_s2 --cache cache_gs [--fecha 2026-02-06]

Junta las teselas de una misma pasada (mismo día, misma órbita) en una grilla de 20 m y
deja cache/ndvi_s2.tif con el mismo formato que fuentes.ndvi_sentinel2, que luego lo lee
desde la caché sin consultar STAC.
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely.geometry import box, shape
from shapely.ops import unary_union

from . import config, fuentes

log = logging.getLogger("verdeh3")


def teselas_de_una_pasada(bbox, fecha: str | None = None):
    items = list(fuentes._stac().search(collections=["sentinel-2-l2a"], bbox=bbox, datetime=config.VERANO,
                                        query={"eo:cloud_cover": {"lt": config.NUBES_MAX_S2}}).items())
    por_dia = {}
    for i in items:
        por_dia.setdefault(str(i.datetime.date()), {}).setdefault(i.id.split("_")[4], i)  # una por tesela
    zona = box(*bbox)
    candidatas = {d: list(t.values()) for d, t in por_dia.items()
                  if unary_union([shape(i.geometry) for i in t.values()]).contains(zona)}
    if fecha:
        candidatas = {d: v for d, v in candidatas.items() if d == fecha}
    if not candidatas:
        raise RuntimeError("Sin pasada Sentinel-2 que cubra el bbox con las teselas de un mismo día")
    dia = min(candidatas, key=lambda d: max(i.properties["eo:cloud_cover"] for i in candidatas[d]))
    log.info("Pasada %s: %s", dia, ", ".join(i.id for i in candidatas[dia]))
    return candidatas[dia]


def ndvi_mosaico(bbox, cache: Path, fecha: str | None = None) -> Path:
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.merge import merge
    from rasterio.warp import transform_bounds

    ruta = cache / "ndvi_s2.tif"
    its = teselas_de_una_pasada(bbox, fecha)
    res = 10 * config.DECIMACION_S2

    def mosaico(banda, resampling):
        fuentes_ = [rasterio.open(i.assets[banda].href) for i in its]
        try:
            crs = fuentes_[0].crs
            assert all(s.crs == crs for s in fuentes_), "teselas en distinta zona UTM"
            b = transform_bounds(config.CRS_GEO, crs, *bbox)
            b = (b[0] // res * res, b[1] // res * res, -(-b[2] // res) * res, -(-b[3] // res) * res)
            arr, t = merge(fuentes_, bounds=b, res=res, nodata=0, resampling=resampling)
            return arr[0], t, crs
        finally:
            for s in fuentes_:
                s.close()

    b04, t, crs = mosaico("B04", Resampling.average)
    b08, _, _ = mosaico("B08", Resampling.average)
    scl, _, _ = mosaico("SCL", Resampling.nearest)
    base = min(str(i.properties.get("s2:processing_baseline", "04.00")) for i in its)
    offset = 1000 if base >= "04.00" else 0
    rojo = (b04.astype("float64") - offset) / 10_000
    nir = (b08.astype("float64") - offset) / 10_000
    with np.errstate(invalid="ignore", divide="ignore"):
        ndvi = (nir - rojo) / (nir + rojo)
    ndvi[(b04 == 0) | np.isin(scl, [0, 1, 3, 8, 9, 10, 11])] = np.nan
    fuentes._guardar_tif(ruta, np.clip(ndvi, -1, 1), t, crs,
                         {"escena": ",".join(i.id for i in its), "fecha": its[0].datetime.date()})
    log.info("NDVI mosaico %s: %s px, %.1f%% válido", ruta, ndvi.shape, 100 * np.isfinite(ndvi).mean())
    return ruta


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--comunas", nargs="+", help="Por defecto todas las de cache/comunas.gpkg")
    p.add_argument("--cache", type=Path, required=True)
    p.add_argument("--fecha", help="Día de la pasada (AAAA-MM-DD); por defecto la de menos nubes")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    comunas = gpd.read_file(a.cache / "comunas.gpkg")
    if a.comunas:
        comunas = comunas[comunas["comuna"].isin(a.comunas)]
    area = comunas.union_all().intersection(box(*config.BBOX_URBANO))
    ndvi_mosaico(tuple(round(v, 5) for v in area.bounds), a.cache, a.fecha)


if __name__ == "__main__":
    main()
