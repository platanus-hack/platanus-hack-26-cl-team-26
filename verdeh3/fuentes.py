"""Descarga y caché de las fuentes (OSM, Sentinel-2, Landsat, WorldPop).

Todo queda en cache/ como archivos locales recortados: la demo nunca consulta APIs en vivo.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import requests

from . import config

log = logging.getLogger(__name__)


def descargar(url: str, destino: Path) -> Path:
    if destino.exists() and destino.stat().st_size > 0:
        return destino
    log.info("Descargando %s", url)
    tmp = destino.with_suffix(destino.suffix + ".part")
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for bloque in r.iter_content(1 << 20):
                f.write(bloque)
    tmp.rename(destino)
    return destino


# ---------------------------------------------------------------- OpenStreetMap
_KV = re.compile(r'"((?:[^"\\]|\\.)*)"=>"((?:[^"\\]|\\.)*)"')
CLAVES_OSM = ["amenity", "healthcare", "railway", "public_transport", "station", "subway", "bus",
              "highway", "social_facility", "leisure", "landuse", "place", "name"]


def _expandir_tags(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    otros = gdf.get("other_tags", pd.Series(None, index=gdf.index)).fillna("")
    parsed = otros.map(lambda s: dict(_KV.findall(s)))
    for k in CLAVES_OSM:
        desde_otros = parsed.map(lambda d: d.get(k))
        gdf[k] = gdf[k].fillna(desde_otros) if k in gdf.columns else desde_otros
    return gdf


def leer_osm(pbf: Path, bbox: tuple) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Lee puntos y multipolígonos del extracto OSM (driver OSM de GDAL) dentro de bbox.

    Devuelve (areas_crudas, poi_crudos) con las mismas columnas que entrega OSMnx,
    para reutilizar la limpieza de ingesta.procesamiento."""
    import pyogrio

    capas = []
    for capa in ("points", "multipolygons"):
        log.info("Leyendo capa OSM %s (puede tardar unos minutos la primera vez)", capa)
        g = pyogrio.read_dataframe(pbf, layer=capa, bbox=bbox)
        g = _expandir_tags(g)
        g["element"] = "node" if capa == "points" else "way"
        g["id"] = g["osm_id"] if "osm_id" in g else g.get("osm_way_id")
        capas.append(g)
    todo = gpd.GeoDataFrame(pd.concat(capas, ignore_index=True), crs=capas[0].crs)

    verde = (todo["leisure"].isin(["park", "garden", "nature_reserve", "playground", "pitch_grass"])
             | todo["landuse"].isin(["recreation_ground", "village_green", "grass", "forest"])
             | (todo["place"] == "square"))
    areas = todo[verde & todo.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    areas = areas.set_index(["element", "id"])

    poi = todo[todo["amenity"].isin(["school", "kindergarten", "college", "university", "hospital",
                                     "clinic", "doctors"])
               | todo["healthcare"].notna() | todo["railway"].isin(["station", "subway_entrance", "halt"])
               | todo["public_transport"].isin(["station", "platform"]) | (todo["highway"] == "bus_stop")
               | (todo["social_facility"] == "nursing_home")].copy()
    log.info("OSM: %d áreas verdes crudas, %d POIs crudos", len(areas), len(poi))
    return areas, poi


# ----------------------------------------------------------------- satelital
def _stac():
    import planetary_computer
    import pystac_client
    return pystac_client.Client.open(config.STAC_URL, modifier=planetary_computer.sign_inplace)


def _mejor_escena(coleccion: str, bbox, nubes_max: int, extra_query: dict | None = None):
    from shapely.geometry import box, shape
    q = {"eo:cloud_cover": {"lt": nubes_max}}
    q.update(extra_query or {})
    items = list(_stac().search(collections=[coleccion], bbox=bbox, datetime=config.VERANO, query=q).items())
    if not items:
        raise RuntimeError(f"Sin escenas {coleccion} con nubes < {nubes_max}% en {config.VERANO}")
    zona = box(*bbox)
    cubren = [i for i in items if shape(i.geometry).contains(zona)]
    if not cubren:
        raise RuntimeError(f"Ninguna escena {coleccion} cubre todo el bbox {bbox}; achica el área")
    mejor = sorted(cubren, key=lambda i: i.properties["eo:cloud_cover"])[0]
    log.info("Escena %s: %s (%s, nubes %.1f%%)", coleccion, mejor.id, mejor.datetime.date(),
             mejor.properties["eo:cloud_cover"])
    return mejor


def _leer_recorte(href: str, bbox, decimacion: int = 1, resampling="average"):
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.warp import transform_bounds
    from rasterio.windows import from_bounds

    with rasterio.open(href) as src:
        b = transform_bounds(config.CRS_GEO, src.crs, *bbox)
        win = from_bounds(*b, transform=src.transform).round_offsets().round_lengths()
        alto, ancho = int(win.height // decimacion), int(win.width // decimacion)
        arr = src.read(1, window=win, out_shape=(alto, ancho), resampling=getattr(Resampling, resampling))
        t = rasterio.windows.transform(win, src.transform) * rasterio.Affine.scale(win.width / ancho, win.height / alto)
        return arr, t, src.crs


def _guardar_tif(ruta: Path, arr, transform, crs, meta: dict):
    import rasterio
    with rasterio.open(ruta, "w", driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1,
                       dtype="float32", crs=crs, transform=transform, nodata=np.nan, compress="deflate") as dst:
        dst.write(arr.astype("float32"), 1)
        dst.update_tags(**{k: str(v) for k, v in meta.items()})


def _leer_tif(ruta: Path):
    import rasterio
    with rasterio.open(ruta) as src:
        return src.read(1), src.transform, src.crs, src.tags()


def ndvi_sentinel2(bbox, cache: Path):
    ruta = cache / "ndvi_s2.tif"
    if not ruta.exists():
        it = _mejor_escena("sentinel-2-l2a", bbox, config.NUBES_MAX_S2)
        d = config.DECIMACION_S2
        b04, t, crs = _leer_recorte(it.assets["B04"].href, bbox, d)
        b08, _, _ = _leer_recorte(it.assets["B08"].href, bbox, d)
        scl, _, _ = _leer_recorte(it.assets["SCL"].href, bbox, d // 2 or 1, "nearest")
        if scl.shape != b04.shape:  # SCL es de 20 m: llevar a la grilla de B04
            fi = (np.arange(b04.shape[0]) * scl.shape[0] / b04.shape[0]).astype(int)
            ci = (np.arange(b04.shape[1]) * scl.shape[1] / b04.shape[1]).astype(int)
            scl = scl[np.ix_(fi, ci)]
        # Desde el procesamiento 04.00 (2022) los DN llevan un offset de +1000.
        offset = 1000 if str(it.properties.get("s2:processing_baseline", "04.00")) >= "04.00" else 0
        rojo = (b04.astype("float64") - offset) / 10_000
        nir = (b08.astype("float64") - offset) / 10_000
        with np.errstate(invalid="ignore", divide="ignore"):
            ndvi = (nir - rojo) / (nir + rojo)
        ndvi[(b04 == 0) | np.isin(scl, [0, 1, 3, 8, 9, 10, 11])] = np.nan  # nubes, sombra, sin dato
        _guardar_tif(ruta, np.clip(ndvi, -1, 1), t, crs, {"escena": it.id, "fecha": it.datetime.date()})
    return _leer_tif(ruta)


def lst_landsat(bbox, cache: Path):
    ruta = cache / "lst_landsat.tif"
    if not ruta.exists():
        it = _mejor_escena("landsat-c2-l2", bbox, config.NUBES_MAX_LANDSAT,
                           {"platform": {"in": ["landsat-8", "landsat-9"]}})
        st, t, crs = _leer_recorte(it.assets["lwir11"].href, bbox, 1, "nearest")
        lst = st.astype("float64") * 0.00341802 + 149.0 - 273.15  # Collection 2 L2 -> °C
        lst[st == 0] = np.nan
        _guardar_tif(ruta, lst, t, crs, {"escena": it.id, "fecha": it.datetime.date()})
    return _leer_tif(ruta)


def poblacion_worldpop(bbox, cache: Path, tif_local: Path | None = None):
    ruta = cache / "poblacion_recorte.tif"
    if not ruta.exists():
        fuente = tif_local
        if fuente is None:
            for url in config.URLS_WORLDPOP:
                try:
                    fuente = descargar(url, cache / Path(url).name)
                    break
                except Exception as e:  # noqa: BLE001
                    log.warning("WorldPop no disponible en %s: %s", url, e)
            if fuente is None:
                raise RuntimeError("No se pudo bajar WorldPop; usa --poblacion-tif")
        arr, t, crs = _leer_recorte(str(fuente), bbox, 1, "nearest")
        arr = arr.astype("float64")
        arr[(arr < 0) | (arr > 1e6)] = np.nan
        _guardar_tif(ruta, arr, t, crs, {"fuente": Path(str(fuente)).name})
    return _leer_tif(ruta)
