# VerdeH3 · respaldo

Base geoespacial en grilla Uber H3 (res 8 y 9) para Providencia, Las Condes, Estación Central y Cerro Navia:
NDVI, temperatura de superficie, áreas verdes, servicios cercanos y población por hexágono.

**Los datos ya calculados están en `datos/`**, así que la demo corre sin internet:

- `datos/salida_h3/santiago_h3.parquet`: tabla final (GeoParquet, EPSG:4326, res 8 y 9 en la columna `res`).
- `datos/salida_h3/capas_osm.gpkg`: áreas verdes y POIs limpios de OSM.
- `datos/salida_h3/resumen_h3.json`: resumen por comuna y estado de cada fuente.
- `datos/cache/`: rásters recortados (`ndvi_s2.tif`, `lst_landsat.tif`, `poblacion_recorte.tif`) y `comunas.gpkg`.

Para regenerarlos:

```bash
pip install -r requirements.txt
python -m verdeh3.pipeline --cache datos/cache --salida datos/salida_h3
```

El extracto OSM de Chile (`chile-latest.osm.pbf`, ~350 MB, Geofabrik) se baja solo la primera vez.

Escenas usadas:

- NDVI: Sentinel-2 `S2B_MSIL2A_20260206T143739_R096_T19HCD` (2026-02-06, 0 % nubes).
- LST: Landsat 8 `LC08_L2SP_233083_20260211_02_T1` (2026-02-11, 0,3 % nubes).

Advertencias:

- Las Condes incluye precordillera: filtra los hexágonos con `poblacion < 50` antes de comparar comunas
  (si no, el % de área verde sube por bosques y reservas).
- Para totales de población por comuna, pondera cada hexágono por `frac_en_estudio`; los hexágonos de borde
  traen su población completa y la suma simple la infla.

Prueba offline: `python -m tests.test_h3_sintetico`.

## Gran Santiago (34 comunas)

Las 32 comunas de la Provincia de Santiago más Puente Alto y San Bernardo, recortadas a `BBOX_URBANO`.
Van aparte de las 4 comunas de arriba, que no cambian:

- `datos/salida_h3_gs/santiago_h3.parquet`: 1.956 hexágonos res 8 y 13.172 res 9, mismas columnas más
  `elev_m`, `precordillera` (≥ 900 m), `baja_poblacion` (< 500 hab/km²) y `comuna_piloto` (las 4 originales).
- `datos/salida_h3_gs/capas_osm.gpkg` y `resumen_h3.json`.
- `datos/cache_gs/`: rásters recortados al área completa, más `elev_cop30.tif` (Copernicus DEM 30 m).

Para regenerarlos (los rásters de caché no llevan el bbox en el nombre, por eso van en otra carpeta):

```bash
python -m verdeh3.mosaico_s2 --cache datos/cache_gs --fecha 2026-02-06   # ninguna tesela S2 cubre sola el área
python -m verdeh3.pipeline --cache datos/cache_gs --salida datos/salida_h3_gs --comunas Cerrillos "Cerro Navia" \
  Conchalí "El Bosque" "Estación Central" Huechuraba Independencia "La Cisterna" "La Florida" "La Granja" \
  "La Pintana" "La Reina" "Las Condes" "Lo Barnechea" "Lo Espejo" "Lo Prado" Macul Maipú Ñuñoa \
  "Pedro Aguirre Cerda" Peñalolén Providencia Pudahuel Quilicura "Quinta Normal" Recoleta Renca \
  "San Joaquín" "San Miguel" "San Ramón" Santiago Vitacura "Puente Alto" "San Bernardo"
python -m verdeh3.marcar_gs --cache datos/cache_gs --salida datos/salida_h3_gs
```

NDVI: mosaico de `S2A_MSIL2A_20260206T144901_R096_T19HCD` y `..._T19HCC` (2026-02-06). LST: la misma escena Landsat.

Advertencias:

- Para sacar el cerro usa `precordillera`; `baja_poblacion` también atrapa parques, aeropuerto e industrias.
- El contrato v3 usa el Censo 2024 (`poblacion_censo`). WorldPop 2020 constrained (`poblacion`) reparte mal la población entre comunas (Maipú 1,58 M, Puente Alto 1,13 M,
  Santiago 135 k; total 7,6 M). Sirve para comparar densidades, no para cifras por comuna.

## Contrato v3 y optimizador (Rol 1)

Ver `CONTRATO.md` y `NOTAS PITCH.md` (cifras verificadas y límites del modelo). Comunas de la demo: Providencia y Cerro Navia.

```bash
python -m verdeh3.landsat       # lst_c con la última escena de verano (dic-feb); --modo ultima agrega la más reciente
python -m verdeh3.worldcover    # árboles, pasto y construido (ESA WorldCover 2021) en datos/salida_h3_gs
python -m verdeh3.censo         # población Censo 2024 por manzana (zip del INE en cache/censo2024/, no versionado)
python -m verdeh3.arboles       # árboles estimados con la altura de copa de Meta y WRI (baja 332 MB a cache/)
python -m verdeh3.modelo_copa   # modelo propio de copa: Sentinel-2 entrenado con Meta; el índice usa su copa_modelo_pct
python -m verdeh3.impact        # % de árboles de Impact Observatory (solo comparación)
python -m verdeh3.contrato      # data/santiago_h3.parquet, _mock, _gs (34 comunas) y data/cifras_pitch.json
python -m tests.test_contrato
```

`optimizer.solve_corridor(df, budget_km=3.0, w_calor=0.4, w_arbol=0.4, w_personas=0.2, live=None)` devuelve el
corredor continuo entre parques que más urgencia cubre dentro del presupuesto.

## App web: mapa + captura en terreno (un solo servidor)

`python -m terreno.servidor` sirve todo (FastAPI, sin Streamlit):

- `/mapa` (laptop o jurado): tres vistas sobre la grilla H3.
  - *Tiempo real*: capas de calor (LST más reciente, o temperatura del aire en vivo por barrio si hay
    `data/live_h3.parquet`), verde (copa + NDVI) y social/densidad; con varias capas el color es el promedio RGB.
  - *Corredor*: Dijkstra con presupuesto (km) y pesos calor / árboles / personas, métricas contra caminatas al
    azar y el efecto de las fotos de terreno.
  - *Histórico*: promedio de LST y NDVI de las escenas entre dos fechas (`data/historico_h3.parquet`, 2023–2026).
  - Área: comunas (toque en el mapa, «Piloto», «Todas (34)»), distritos (barrios H3 res 7) y «Encerrar zona»
    para dibujar un polígono. Presupuesto, pesos y área son compartidos: la captura del teléfono responde con
    los mismos números que muestra el mapa.
- `/captura?k=<clave>` (teléfono): captura en terreno, abajo.

### Despliegue en Render (un solo servicio)

El `Dockerfile` compila el sitio Viridis (`web/`, `npm run exportar` → archivos estáticos en `web/out`) y lo
sirve desde el mismo servidor de terreno. Un solo enlace: `/` el sitio, `/api` los datos, `/captura` el teléfono
(HTTPS de Render, que el GPS exige) y `/mapa` el mapa de respaldo.

1. En Render: **New → Blueprint**, elegir este repositorio (rama `main`); `render.yaml` crea el servicio
   `viridis` (plan standard, 2 GB: el modelo de aves no cabe holgado en 512 MB) con un disco de 1 GB en
   `data/terreno/` para que las capturas sobrevivan a cada despliegue.
2. En **Environment**, escribir los secretos (nunca en el repo): `TERRENO_CLAVE` (clave de subida del
   teléfono), `ANTHROPIC_API_KEY` (Claude valida las fotos), `DMC_USUARIO` y `DMC_TOKEN` (estaciones DMC del
   aire en vivo).
3. Health check: `/api/salud`. Cada push a `main` vuelve a desplegar.

Para probarlo igual en local: `cd web && npm run exportar`, y luego `python -m terreno.servidor` sirve todo en
http://localhost:8000.

## Captura en terreno (teléfono → corredor en vivo)

**Fauna para los corredores.** Un corredor verde sirve para conectar hábitat, así que el equipo también
registra fauna en terreno:
- Fotos y videos: Claude anota aves, abejas, mariposas y flores que se vean con claridad. Un primer plano
  exterior de un ave, un insecto o una flor es válido («fauna_flora»): suma biodiversidad y no cambia la copa
  ni el espacio para plantar del hexágono.
- «🎙️ Escuchar aves (15 s)»: el teléfono graba 15 s (WAV, sin cancelación de ruido) y BirdNET identifica las
  aves por su canto, solo entre las esperables en Santiago esa semana del año (`terreno/aves.py`, sin red).
  Nombres científicos y comunes en inglés (el modelo no trae español). Funciona caminando por la calle.
- El video del recorrido también escucha: el micrófono graba mientras se camina, BirdNET oye el audio entero y
  cada ave queda en el hexágono donde iba el teléfono cuando cantó (una escucha por hexágono recorrido, con su
  trozo de audio en el mapa).
- Ruido de la calle: cada escucha mide el tráfico (banda 100–1500 Hz, dB relativos del micrófono, no
  calibrados): bajo, medio o alto. BirdNET tolera el ruido de fondo, pero el tráfico fuerte tapa aves lejanas y
  arrullos graves; sin aves y con ruido alto la escucha queda «no concluyente».
- Cada hexágono suma una biodiversidad de 0 a 1 (ver `CONTRATO.md`) que entra al corredor con el peso
  «Biodiversidad (terreno)» del mapa (10 de 100 al inicio). En el mapa: capa de biodiversidad, marcadores 🎧
  con el audio y especies, y «Especies de aves en el corredor».
- Honestidad: no detectar fauna no significa que no haya, y un hexágono sin visitar vale 0; por eso el peso es
  bajo y el resultado se lee como «dónde encontramos evidencia». BirdNET: K. Lisa Yang Center for Conservation
  Bioacoustics (Cornell), modelo CC BY-NC-SA 4.0 (uso no comercial).

El equipo recorre el corredor con un teléfono: cada foto lleva GPS, se analiza (índice de verde siempre;
Claude estima árboles, espacio para plantar y obstáculos si hay credenciales de Anthropic), actualiza su
hexágono en `data/terreno_h3.parquet` (ver `CONTRATO.md`) y `optimizer.solve_corridor` recalcula el corredor.
El mapa en vivo muestra el corredor antes y después de las fotos.

```bash
python -m venv .venv && .venv/Scripts/pip install h3 pandas numpy pyarrow fastapi uvicorn python-multipart pillow anthropic httpx
set TERRENO_CLAVE=una-clave                        # la URL del túnel es pública: la clave protege la subida
.venv/Scripts/python -m terreno.servidor           # --sin-claude para usar solo el índice de verde
cloudflared tunnel --url http://localhost:8000     # entrega https://<algo>.trycloudflare.com
```

- Teléfono: `https://<algo>.trycloudflare.com/?k=una-clave` (el GPS del navegador exige HTTPS). Aceptar la
  ubicación, esperar precisión ≤ 30 m, «Tomar foto», «Subir captura».
- Mapa para proyectar: `http://localhost:8000/mapa` (consulta cada 3 s y redibuja solo si algo cambió).
  Por el túnel o en Render, abrir `/mapa?k=una-clave` para poder cambiar comunas y pesos.
- Comunas: el servidor carga las 34 comunas (`data/santiago_h3_gs.parquet`) y calcula el corredor solo en las
  elegidas. Al abrir se ven las 34 («Todas las comunas»); «Por comuna» separa el análisis (o `--comunas ...` al
  iniciar). En modo por comuna, tocar una comuna vecina (borde punteado) la
  suma; tocar otra comuna empieza de nuevo ahí; tocar dentro de una elegida muestra el hexágono con un botón
  para quitarla; la × de cada comuna también la quita. Las fotos de cualquier comuna se
  guardan y cuentan cuando esa comuna está elegida.
- Video: «Abrir cámara de video» abre la cámara a pantalla completa; el botón rojo graba dentro de la página (máx. 3 min) mientras registra el trazado GPS; cada 3 s
  guarda un cuadro con su posición y hora. Al subirlo se analizan hasta 12 cuadros (2 por hexágono como máximo),
  cada uno valida su propio hexágono, y el mapa dibuja el recorrido en morado con enlace al video. No se aceptan
  videos de la galería: sin trazado GPS no se sabe dónde fue cada cuadro.
- Cada captura guarda posición (lat, lon, precisión del GPS en m), `tomado_en` (hora del teléfono) y `medido_en`
  (hora de llegada al servidor).
- Claude: usa `ANTHROPIC_API_KEY`, un perfil de `ant auth login` o la key sola en `.anthropic_key` (raíz del
  repo, en `.gitignore`). Claude primero valida que sea una foto
  exterior de calle o espacio público (descarta interiores, vistas desde ventanas, pantallas, primeros planos).
- Solo las fotos válidas cambian el corredor. Sin credenciales, las fotos quedan «sin validar» (el índice de
  verde no distingue una oficina de una calle) y no cuentan; `--aceptar-sin-validar` las deja contar en una
  demo sin red.
- Las fotos se guardan sin EXIF en `data/terreno/fotos/`. Ni las fotos ni los registros
  (`data/terreno/*.jsonl`, con la posición GPS de cada captura y recorrido) ni `data/terreno_h3.parquet` se
  versionan: quedan en el computador que corre el servidor.
- Prueba offline: `python -m tests.test_terreno`.

Honestidad: una foto de calle muestra parte de un hexágono de ~0,1 km²; complementa al satélite (el déficit de
árboles del hexágono es el promedio 50/50 entre el de `copa_modelo_pct` y el de la foto) y no lo reemplaza. Los porcentajes de Claude son estimaciones visuales.

# Corredores Verdes · Bloque 1

Ingesta geoespacial del Gran Santiago: `python -m ingesta.pipeline` (ver `ingesta/pipeline.py`).
