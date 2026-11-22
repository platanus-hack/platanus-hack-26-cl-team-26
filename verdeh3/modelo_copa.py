"""Modelo propio de copa de árboles: Sentinel-2 (10 m) entrenado con la altura de copa de Meta y WRI.

python -m verdeh3.modelo_copa

Etiqueta: % de cada píxel de 10 m con vegetación de 3 m o más en el mapa de Meta (1 m, imágenes de
oct-nov 2019). Entrenamiento con una pasada Sentinel-2 de la misma temporada (8 de febrero de 2020);
predicción con la pasada equivalente más reciente (6 de febrero de 2026), mismo mes para igualar el ángulo
del sol y la fenología. Modelo: gradient boosting por píxel (scikit-learn).
Se probó agregar el NDVI de invierno: en 2020 casi no mejora (r 0,921 contra 0,915 por hexágono) y empeora
la coherencia del mapa 2026 (0,79 contra 0,82), porque el invierno de 2019 fue de sequía y el de 2025 no.

Validación: 5 grupos de comunas; cada comuna se predice con un modelo que nunca la vio. Las métricas
quedan en data/modelo_copa.json. La predicción 2026 no tiene verdad de terreno de 2026: solo se puede
comprobar que el modelo acierta en 2020 y que el mapa 2026 es coherente con el de 2019.

El modelo entrenado queda en datos/modelo_copa.joblib (scikit-learn). Agrega a santiago_h3.parquet (res 9):
  copa_modelo_pct        % de copa predicho con las imágenes de 2026
  copa_modelo_2020_pct   % de copa predicho para 2020 sin haber visto la comuna (validación)
"""
from __future__ import annotations

import argparse
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.merge import merge
from rasterio.warp import reproject, transform_bounds
from rasterio.windows import from_bounds
from scipy import ndimage

from . import config, fuentes

log = logging.getLogger("verdeh3")

PASADAS = {"entrena": "2020-02-08", "actual": "2026-02-06"}
BANDAS = ["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12"]
SCL_MALO = [0, 1, 3, 8, 9, 10, 11]  # sin dato, saturado, sombra de nube, nubes, cirros, nieve
ALTURA_MIN_M = 3
N_GRUPOS = 5
MUESTRA = 600_000
SEMILLA = 0


# ------------------------------------------------------------------ Sentinel-2
def grilla_10m(bbox):
    b = transform_bounds(config.CRS_GEO, config.CRS_METRICO, *bbox)
    b = (b[0] // 20 * 20, b[1] // 20 * 20, -(-b[2] // 20) * 20, -(-b[3] // 20) * 20)
    forma = (int((b[3] - b[1]) / 10), int((b[2] - b[0]) / 10))
    return b, rasterio.transform.from_origin(b[0], b[3], 10, 10), forma


def leer_pasada(fecha: str, bandas: list[str], bbox, cache: Path) -> dict[str, np.ndarray]:
    """Reflectancia 0..1 por banda en la grilla de 10 m (NaN donde hay nube, sombra o no hay dato)."""
    ruta = cache / f"s2_{fecha}_{'-'.join(bandas)}.npz"
    if not ruta.exists():
        its = {}
        for i in fuentes._stac().search(collections=["sentinel-2-l2a"], bbox=bbox, datetime=fecha).items():
            its.setdefault(i.id.split("_")[4], i)
        its = list(its.values())
        bases = {str(i.properties["s2:processing_baseline"]) for i in its}
        assert len(bases) == 1, f"teselas con distinto procesamiento: {bases}"
        offset = 1000 if bases.pop() >= "04.00" else 0  # desde 04.00 los DN llevan +1000
        b, _, forma = grilla_10m(bbox)
        log.info("Pasada %s: %s (offset %d)", fecha, ", ".join(i.id for i in its), offset)

        def una(banda):
            srcs = [rasterio.open(i.assets[banda].href) for i in its]
            try:
                assert all(str(s.crs) == config.CRS_METRICO for s in srcs)
                r = Resampling.nearest if banda == "SCL" or srcs[0].res[0] == 10 else Resampling.bilinear
                arr = merge(srcs, bounds=b, res=10, nodata=0, resampling=r)[0][0]
            finally:
                for s in srcs:
                    s.close()
            assert arr.shape == forma, (banda, arr.shape, forma)
            return arr

        with ThreadPoolExecutor(6) as ex:
            crudo = dict(zip(bandas + ["SCL"], ex.map(una, bandas + ["SCL"])))
        malo = np.isin(crudo.pop("SCL"), SCL_MALO)
        salida = {}
        for k, dn in crudo.items():
            v = np.clip(dn.astype("int32") - offset, 0, 20000).astype("int16")
            v[(dn == 0) | malo] = -1
            salida[k] = v
        np.savez(ruta, **salida)
    with np.load(ruta) as z:
        return {k: np.where(z[k] < 0, np.nan, z[k] / 10_000).astype("float32") for k in z.files}


def _ind(a, b):
    with np.errstate(invalid="ignore", divide="ignore"):
        return ((a - b) / (a + b)).astype("float32")


def variables(ver: dict) -> tuple[list[str], list[np.ndarray]]:
    ndvi = _ind(ver["B08"], ver["B04"])
    nir = np.nan_to_num(ver["B08"])
    media, media2 = ndimage.uniform_filter(nir, 3), ndimage.uniform_filter(nir * nir, 3)
    extra = {
        "ndvi": ndvi,
        "ndmi": _ind(ver["B8A"], ver["B11"]), "ndre": _ind(ver["B8A"], ver["B05"]),
        "textura_nir_3x3": np.sqrt(np.clip(media2 - media * media, 0, None)).astype("float32"),
        "ndvi_vecindad_5x5": ndimage.uniform_filter(np.nan_to_num(ndvi), 5).astype("float32"),
    }
    return BANDAS + list(extra), [ver[b] for b in BANDAS] + list(extra.values())


def matriz(epoca: str, bbox, cache: Path, mascara: np.ndarray) -> tuple[list[str], np.ndarray]:
    nombres, capas = variables(leer_pasada(PASADAS[epoca], BANDAS, bbox, cache))
    return nombres, np.stack([c[mascara] for c in capas], axis=1)


# ------------------------------------------------------------------- etiquetas
def copa_meta_10m(chm: Path, bbox, cache: Path) -> np.ndarray:
    """% de cada píxel de 10 m con altura >= 3 m en el mapa de Meta (promedio del binario de 1 m)."""
    ruta = cache / "copa_meta_10m.npy"
    if ruta.exists():
        return np.load(ruta)
    _, t10, forma = grilla_10m(bbox)
    binario = cache / "copa_meta_1m.tif"
    with rasterio.open(chm) as src:
        win = from_bounds(*transform_bounds(config.CRS_GEO, src.crs, *bbox), transform=src.transform)
        win = win.round_offsets().round_lengths()
        perfil = dict(driver="GTiff", dtype="uint8", count=1, crs=src.crs, compress="deflate",
                      transform=src.window_transform(win), width=int(win.width), height=int(win.height),
                      tiled=True, blockxsize=512, blockysize=512, BIGTIFF="YES")
        with rasterio.open(binario, "w", **perfil) as dst:
            for f0 in range(0, int(win.height), 4096):
                n = min(4096, int(win.height) - f0)
                w = rasterio.windows.Window(win.col_off, win.row_off + f0, win.width, n)
                dst.write((src.read(1, window=w) >= ALTURA_MIN_M).astype("uint8") * 100, 1,
                          window=rasterio.windows.Window(0, f0, win.width, n))
    copa = np.zeros(forma, "float32")
    with rasterio.open(binario) as src:
        reproject(rasterio.band(src, 1), copa, dst_transform=t10, dst_crs=config.CRS_METRICO,
                  resampling=Resampling.average, num_threads=8)
    binario.unlink()
    np.save(ruta, copa)
    return copa


# ---------------------------------------------------------------------- modelo
def _modelo():
    from sklearn.ensemble import HistGradientBoostingRegressor
    return HistGradientBoostingRegressor(max_iter=300, learning_rate=0.08, max_leaf_nodes=63,
                                         min_samples_leaf=50, random_state=SEMILLA)


def _metricas(y, p) -> dict:
    e = p - y
    return {"n": int(len(y)), "r": round(float(np.corrcoef(y, p)[0, 1]), 3),
            "r2": round(float(1 - (e ** 2).sum() / ((y - y.mean()) ** 2).sum()), 3),
            "mae": round(float(np.abs(e).mean()), 2), "sesgo": round(float(e.mean()), 2)}


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--salida", type=Path, default=Path("datos/salida_h3_gs"))
    p.add_argument("--cache", type=Path, default=Path("cache/s2_modelo"))
    p.add_argument("--chm", type=Path, default=Path("cache/meta_chm/chm_210231031.tif"))
    p.add_argument("--data", type=Path, default=Path("data"))
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    a.cache.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEMILLA)

    ruta = a.salida / "santiago_h3.parquet"
    tabla = gpd.read_parquet(ruta)
    bbox = tuple(round(float(v), 5) for v in tabla.total_bounds)
    h9 = tabla[tabla["res"] == 9].reset_index(drop=True)
    _, t10, forma = grilla_10m(bbox)
    ids = rasterize(zip(h9.to_crs(config.CRS_METRICO).geometry, range(1, len(h9) + 1)), out_shape=forma,
                    transform=t10, fill=0, dtype="int32")
    mascara = ids > 0
    hex_px = ids[mascara] - 1
    comuna_px = pd.Categorical(h9["comuna"]).codes[hex_px]
    comunas = pd.Categorical(h9["comuna"]).categories
    log.info("Grilla %s, %d píxeles en hexágonos", forma, mascara.sum())

    y = copa_meta_10m(a.chm, bbox, a.cache)[mascara]
    nombres, X = matriz("entrena", bbox, a.cache, mascara)
    ok = np.isfinite(X).all(axis=1)
    log.info("Entrenamiento: %.1f%% de píxeles válidos, copa media Meta %.1f%%", 100 * ok.mean(), y[ok].mean())

    # Validación: cada comuna se predice con un modelo entrenado sin ella.
    grupo = rng.permutation(len(comunas)) % N_GRUPOS
    oof = np.full(len(y), np.nan, "float32")
    for g in range(N_GRUPOS):
        fuera = np.isin(comuna_px, np.flatnonzero(grupo == g))
        ent = rng.choice(np.flatnonzero(ok & ~fuera), MUESTRA, replace=False)
        m = _modelo().fit(X[ent], y[ent])
        val = ok & fuera
        oof[val] = np.clip(m.predict(X[val]), 0, 100)
        log.info("Grupo %d (%s): %s", g + 1, ", ".join(comunas[grupo == g]), _metricas(y[val], oof[val]))

    ent = rng.choice(np.flatnonzero(ok), MUESTRA, replace=False)
    final = _modelo().fit(X[ent], y[ent])
    medianas_ent = np.nanmedian(X[ent], axis=0)
    del X

    nombres, X = matriz("actual", bbox, a.cache, mascara)
    ok26 = np.isfinite(X).all(axis=1)
    pred = np.full(len(y), np.nan, "float32")
    pred[ok26] = np.clip(final.predict(X[ok26]), 0, 100)
    med26 = np.nanmedian(X[rng.choice(np.flatnonzero(ok26), MUESTRA, replace=False)], axis=0)
    razon = {n: round(float(med26[j] / medianas_ent[j]), 3) for j, n in enumerate(nombres) if n in BANDAS}
    del X

    def por_hex(v):
        return pd.Series(v).groupby(hex_px).mean().reindex(range(len(h9))).to_numpy()

    h9["copa_modelo_2020_pct"] = por_hex(oof)
    h9["copa_modelo_pct"] = por_hex(pred)
    h9["_meta10"] = por_hex(np.where(ok, y, np.nan))
    urb = ~h9["precordillera"] & h9[["copa_modelo_2020_pct", "copa_modelo_pct", "copa_pct"]].notna().all(axis=1)
    u = h9[urb]
    wc = 100 * u["frac_arboles"]
    resumen = {
        "pasadas": PASADAS, "variables": nombres, "muestra_entrenamiento": MUESTRA,
        "pixel_10m_comunas_no_vistas": _metricas(y[np.isfinite(oof)], oof[np.isfinite(oof)]),
        "hexagono_urbano": {
            "modelo_2020_comunas_no_vistas_vs_meta_2019": _metricas(u["copa_pct"].to_numpy(),
                                                                    u["copa_modelo_2020_pct"].to_numpy()),
            "worldcover_2021_vs_meta_2019": _metricas(u["copa_pct"].to_numpy(), wc.to_numpy()),
            "modelo_2026_vs_meta_2019": _metricas(u["copa_pct"].to_numpy(), u["copa_modelo_pct"].to_numpy()),
            "modelo_2026_vs_modelo_2020": _metricas(u["copa_modelo_2020_pct"].to_numpy(),
                                                    u["copa_modelo_pct"].to_numpy()),
        },
        "control_etiqueta_10m_vs_1m_por_hexagono_r": round(float(np.corrcoef(u["_meta10"], u["copa_pct"])[0, 1]), 4),
        "mediana_2026_sobre_2020_por_banda": razon,
        "demo_por_comuna_pct": u[u["comuna"].isin(["Providencia", "Cerro Navia"])].groupby("comuna")[
            ["copa_pct", "copa_modelo_2020_pct", "copa_modelo_pct"]].mean().astype(float).round(2).to_dict("index"),
        "copa_media_urbana_pct": {"meta_2019": round(float(u["copa_pct"].mean()), 2),
                                  "modelo_2020": round(float(u["copa_modelo_2020_pct"].mean()), 2),
                                  "modelo_2026": round(float(u["copa_modelo_pct"].mean()), 2)},
    }
    a.data.mkdir(exist_ok=True)
    (a.data / "modelo_copa.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(resumen, ensure_ascii=False, indent=2))

    import joblib
    joblib.dump({"modelo": final, "variables": nombres}, a.salida.parent / "modelo_copa.joblib", compress=3)
    for c in ("copa_modelo_2020_pct", "copa_modelo_pct"):
        tabla[c] = tabla["h3"].map(h9.set_index("h3")[c].round(2)).where(tabla["res"] == 9)
    tabla.to_parquet(ruta, index=False)


if __name__ == "__main__":
    main()
