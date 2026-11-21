"""
Descarga serie histórica mensual real de Sentinel-2 (NDVI) y Landsat 8/9 (LST)
desde Microsoft Planetary Computer (2023-01 a 2026-11) para los hexágonos H3 de Santiago.
Guarda el resultado compacto en data/historico_h3.parquet y metadatos en data/historico_meta.json.
"""

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import planetary_computer
import pystac_client
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import transform as warp_transform, transform_bounds
from rasterio.windows import from_bounds
from shapely.geometry import box, shape

from verdeh3 import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("historico")

BASE_DIR = Path(__file__).resolve().parent
RUTA_GS = BASE_DIR / "data" / "santiago_h3_gs.parquet"
RUTA_OUT = BASE_DIR / "data" / "historico_h3.parquet"
RUTA_META = BASE_DIR / "data" / "historico_meta.json"

RANGO_HISTORICO = "2023-01-01/2026-11-21"


def sample_banda(href: str, bbox: tuple, lons: np.ndarray, lats: np.ndarray, decimate_shape=(450, 450)) -> tuple[np.ndarray, str]:
    """Lee una ventana decimated del ráster en la nube y muestrea los centroides H3."""
    with rasterio.open(href) as src:
        b = transform_bounds(config.CRS_GEO, src.crs, *bbox)
        win = from_bounds(*b, transform=src.transform).round_offsets().round_lengths()
        arr = src.read(1, window=win, out_shape=decimate_shape, resampling=Resampling.average)
        t = rasterio.windows.transform(win, src.transform) * rasterio.Affine.scale(
            win.width / decimate_shape[1], win.height / decimate_shape[0]
        )
        xs, ys = warp_transform(config.CRS_GEO, src.crs, lons.tolist(), lats.tolist())
        rows, cols = rasterio.transform.rowcol(t, xs, ys)
        rows = np.clip(rows, 0, decimate_shape[0] - 1)
        cols = np.clip(cols, 0, decimate_shape[1] - 1)
        return arr[rows, cols], str(src.crs)


def mejores_por_mes(items, bbox, max_por_mes=1):
    zona = box(*bbox)
    por_mes = {}
    for it in items:
        try:
            if not shape(it.geometry).contains(zona):
                continue
        except Exception:
            continue
        mes = it.datetime.strftime("%Y-%m")
        nubes = it.properties.get("eo:cloud_cover", 100)
        if mes not in por_mes or nubes < por_mes[mes][0]:
            por_mes[mes] = (nubes, it)
    return {m: v[1] for m, v in sorted(por_mes.items())}


def main():
    df_gs = pd.read_parquet(RUTA_GS, columns=["h3_index", "lat", "lon"])
    lons = df_gs["lon"].to_numpy()
    lats = df_gs["lat"].to_numpy()
    hexs = df_gs["h3_index"].to_numpy()
    bbox = config.BBOX_URBANO

    cat = pystac_client.Client.open(config.STAC_URL, modifier=planetary_computer.sign_inplace)

    # 1. Sentinel-2 L2A (NDVI)
    log.info("Buscando escenas históricas Sentinel-2 (%s)...", RANGO_HISTORICO)
    items_s2 = list(
        cat.search(
            collections=["sentinel-2-l2a"],
            bbox=bbox,
            datetime=RANGO_HISTORICO,
            query={"eo:cloud_cover": {"lt": 15}},
        ).items()
    )
    s2_mes = mejores_por_mes(items_s2, bbox)
    log.info("Sentinel-2: %d meses encontrados (%s a %s)", len(s2_mes), min(s2_mes) if s2_mes else "-", max(s2_mes) if s2_mes else "-")

    # 2. Landsat 8/9 C2 L2 (LST)
    log.info("Buscando escenas históricas Landsat 8/9 (%s)...", RANGO_HISTORICO)
    items_ls = list(
        cat.search(
            collections=["landsat-c2-l2"],
            bbox=bbox,
            datetime=RANGO_HISTORICO,
            query={"eo:cloud_cover": {"lt": 20}, "platform": {"in": ["landsat-8", "landsat-9"]}},
        ).items()
    )
    ls_mes = mejores_por_mes(items_ls, bbox)
    log.info("Landsat: %d meses encontrados (%s a %s)", len(ls_mes), min(ls_mes) if ls_mes else "-", max(ls_mes) if ls_mes else "-")

    todos_meses = sorted(set(s2_mes.keys()) | set(ls_mes.keys()))
    registros = []
    fechas_s2 = []
    fechas_ls = []

    for mes in todos_meses:
        ndvi_vals = np.full(len(hexs), np.nan, dtype="float32")
        lst_vals = np.full(len(hexs), np.nan, dtype="float32")
        fecha_rep = f"{mes}-15"

        if mes in s2_mes:
            it = s2_mes[mes]
            try:
                b04, _ = sample_banda(it.assets["B04"].href, bbox, lons, lats)
                b08, _ = sample_banda(it.assets["B08"].href, bbox, lons, lats)
                offset = 1000 if str(it.properties.get("s2:processing_baseline", "04.00")) >= "04.00" else 0
                rojo = (b04.astype("float64") - offset) / 10_000
                nir = (b08.astype("float64") - offset) / 10_000
                with np.errstate(invalid="ignore", divide="ignore"):
                    ndvi = (nir - rojo) / (nir + rojo)
                ndvi[b04 == 0] = np.nan
                ndvi_vals = np.clip(ndvi, -1, 1).astype("float32")
                fecha_rep = str(it.datetime.date())
                fechas_s2.append(fecha_rep)
                log.info("  [%s] S2 OK (%s, nubes %.1f%%)", mes, fecha_rep, it.properties.get("eo:cloud_cover", 0))
            except Exception as e:
                log.warning("  [%s] S2 error: %s", mes, e)

        if mes in ls_mes:
            it = ls_mes[mes]
            try:
                st_raw, _ = sample_banda(it.assets["lwir11"].href, bbox, lons, lats)
                lst = st_raw.astype("float64") * 0.00341802 + 149.0 - 273.15
                lst[st_raw == 0] = np.nan
                lst_vals = lst.astype("float32")
                f_ls = str(it.datetime.date())
                fechas_ls.append(f_ls)
                if mes not in s2_mes:
                    fecha_rep = f_ls
                log.info("  [%s] Landsat OK (%s, nubes %.1f%%)", mes, f_ls, it.properties.get("eo:cloud_cover", 0))
            except Exception as e:
                log.warning("  [%s] Landsat error: %s", mes, e)

        df_m = pd.DataFrame({
            "mes": mes,
            "fecha": pd.to_datetime(fecha_rep),
            "h3_index": hexs,
            "ndvi": ndvi_vals,
            "lst_c": lst_vals,
        })
        registros.append(df_m)

    if registros:
        df_hist = pd.concat(registros, ignore_index=True)
        df_hist.to_parquet(RUTA_OUT, index=False)
        meta = {
            "total_filas": int(len(df_hist)),
            "meses_totales": len(todos_meses),
            "mes_min": todos_meses[0],
            "mes_max": todos_meses[-1],
            "escenas_sentinel2": len(fechas_s2),
            "escenas_landsat": len(fechas_ls),
            "fechas_s2": fechas_s2,
            "fechas_landsat": fechas_ls,
        }
        RUTA_META.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
        log.info("Guardado %s (%d filas, %.2f MB)", RUTA_OUT, len(df_hist), RUTA_OUT.stat().st_size / 1e6)
    else:
        log.error("No se pudieron descargar escenas históricas.")


if __name__ == "__main__":
    main()
