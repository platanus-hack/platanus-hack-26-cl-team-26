# Contrato de datos · VerdeH3 (plan final v3)

Cambiar algo de este archivo exige avisar a los tres roles. `python -m tests.test_contrato` lo verifica.

## `data/santiago_h3.parquet` (Rol 1)

Una fila por hexágono H3 de resolución 9 de las comunas de la demo (Providencia y Cerro Navia).
Sin nulos y de menos de 5 MB. También existen:

- `data/santiago_h3_mock.parquet`: 30 hexágonos reales y contiguos con valores inventados, para desarrollar.
- `data/santiago_h3_gs.parquet`: las 34 comunas del Gran Santiago, con el mismo esquema.

| Columna | Tipo | Qué es | Fuente |
|---|---|---|---|
| `h3_index` | str | hexágono H3, resolución 9 (cuadra) | `h3` v4 |
| `h3_padre` | str | barrio: `h3.cell_to_parent(h3_index, 7)`, llave para unir `live_h3.parquet` | `h3` v4 |
| `comuna` | str | comuna del centroide | límites comunales |
| `lat`, `lon` | float | centroide | `h3.cell_to_latlng` |
| `lst_c` | float | temperatura superficial, °C | Landsat 8/9 C2 L2, última escena de verano (dic–feb) con < 10% de nubes |
| `ndvi` | float 0–1 | vegetación | Sentinel-2 L2A (B08, B04) |
| `copa_modelo_pct` | float 0–100 | % del hexágono con copa de árboles (≥ 3 m); es el que usa el índice | modelo propio: Sentinel-2 del 6-feb-2026, entrenado con la altura de copa de Meta y WRI (`verdeh3.modelo_copa`) |
| `arbol_pct` | float 0–100 | % con árboles según WorldCover (referencia, ya no entra al índice) | ESA WorldCover 2021 v200, clase 10 |
| `pasto_pct` | float 0–100 | % con pastizal | ESA WorldCover, clase 30 |
| `construido_pct` | float 0–100 | % construido | ESA WorldCover, clase 50 |
| `poblacion` | int | personas en el hexágono | Censo 2024 (INE), personas por manzana repartidas por área |
| `social` | float 0–1 | cercanía a colegios, salud, metro y paraderos: promedio de max(0, 1 − distancia/1 km) | OpenStreetMap |
| `es_parque` | bool | toca un parque consolidado (≥ 5.000 m²) y ≥ 25% del hexágono es área verde | OpenStreetMap |

Columnas extra (pueden ignorarse): `urgencia` y `en_corredor`, calculadas con los pesos por defecto y 3 km;
`lst_fecha` (fecha de la escena de `lst_c`) y `lst_c_ultima` / `lst_fecha_ultima` (escena más reciente
disponible, solo para mostrar; el índice usa la de verano). Árboles, para mostrar y validar (pueden traer
NaN donde no se calcularon): `arboles_meta` (árboles estimados), `altura_copa_m` y `copa_pct_meta` del mapa
de altura de copa de Meta y WRI (1 m, imágenes de oct–nov 2019), y `arbol_pct_io_<año>` de Impact Observatory.
`copa_modelo_2020_pct` es el % de copa que el modelo predice para 2020 en comunas que no vio al entrenar (validación). Las métricas
están en `data/modelo_copa.json`: por hexágono urbano, r = 0,92 y error medio de 1,8 puntos contra Meta 2019.
El mapa 2026 no tiene una referencia medida de 2026 con qué compararlo; no usarlo para afirmar que una cuadra ganó o perdió árboles.

## `optimizer.py` (Rol 1)

```python
solve_corridor(df, budget_km=3.0, w_calor=0.4, w_arbol=0.4, w_personas=0.2, live=None, terreno=None,
               w_bio=0.0) -> dict
```

- `live`: el `data/live_h3.parquet` del Rol 2 (ver abajo). Se une por `h3_padre` sin perder cuadras y se
  usa `temp_aire_c` solo donde `confianza` es "alta" o "media".
- Devuelve `hexes` (list[str]), `length_km`, `urgencia_cubierta` (U media del corredor),
  `urgencia_azar` (U media de corredores al azar del mismo largo) y `personas_cubiertas` (int).
  También trae `personas_azar`, `tramos` (cada tramo es una lista de hexágonos, de parque a parque) y
  `urgencia` (Serie por hexágono, para colorear el mapa).
- `terreno` y `w_bio` quedan en sus valores por omisión (`None` y 0): el proyecto no usa datos de terreno.

Fórmula, con cada término normalizado de 0 a 1 (min-max entre los percentiles 2 y 98):

```
calor    = 0,7·lst_c_norm + 0,3·aire           (aire = 0,5 + (temp_aire_c − mediana)/6 °C, recortado a 0..1;
                                                temp_aire_c del barrio, confianza alta o media)
           sin dato en vivo en esa cuadra, o con menos de cinco barrios con dato: calor = lst_c_norm
           (el aire va en escala fija y no min-max: décimas de grado entre pocos sensores no reordenan el corredor)
falta    = 1 − copa_norm                       (copa_modelo_pct normalizado como los demás términos)
personas = 0,7·poblacion_norm + 0,3·social
U        = (w_calor·calor + w_arbol·falta + w_personas·personas) / (suma de los pesos)
```

Los pesos se pueden mover libremente desde el panel y se reescalan para que sumen 1.
No se usa `indice_calor_c`: en Santiago el aire es seco y el índice de calor no agrega información.
Regla de fidelidad: nunca se inventa un valor en vivo ni se muestra temperatura en vivo por cuadra.

El corredor sale de un grafo de vecindad `h3.grid_disk(h, 1)`. Entrar a un hexágono cuesta `1/(0,05 + U)`
y los parques cuestan 0. Dijkstra entrega el camino más barato entre cada par de parques vecinos, y los
tramos se unen en una sola red continua (parque, tramo, parque…) por orden de urgencia hasta llenar el
presupuesto. Los hexágonos con menos de 50 personas que no son parque (industria, eriazo) no entran al
grafo. Tarda unos 10 ms con la demo y unos 80 ms con las 34 comunas.

No se informan °C de enfriamiento, porque no hay un coeficiente publicado que citar.

## `data/live_h3.parquet` (Rol 2)

Una fila por barrio (H3 resolución 7), no por cuadra. Desde el 21-11-2026 es la **máxima del día anterior**,
no la lectura del momento: lo escribe `maximas.py` una vez al día (GitHub Actions, pasada la medianoche) con
estaciones oficiales (DMC y SINCA). Una estación entra solo si tiene datos en al menos 3 de las 4 horas más
calientes (14 a 18 h); el historial por estación queda en `data/maximas/AAAA-MM-DD.csv`.

| Columna | Tipo | Qué es |
|---|---|---|
| `h3_padre` | str | barrio H3 resolución 7 |
| `temp_aire_c` | float | temperatura máxima del aire del día, °C |
| `humedad_pct` | float | humedad relativa a la hora de la máxima, % |
| `indice_calor_c` | float | índice de calor, °C (informativo) |
| `anomalia_c` | float | diferencia contra lo esperable, °C |
| `n_sensores` | int | sensores que aportan al barrio |
| `dist_min_km` | float | distancia al sensor más cercano |
| `confianza` | str | "alta", "media", "baja" o "sin dato" |
| `medido_en` | timestamp | hora de la máxima (la más reciente entre las estaciones del barrio) |
| `alerta` | bool | opcional |

## `data/fauna_h3.parquet` (aves y abejas registradas, GBIF)

Sección nueva y aditiva: no cambia las tablas de arriba. La escribe `fauna_gbif.py` (se corre a mano, unos minutos)
con registros de GBIF.org (eBird, iNaturalist, museos) con coordenadas, desde 2015. Una fila
por barrio (H3 resolución 7) de la grilla de 34 comunas; no por cuadra, porque muchas ubicaciones tienen un margen
de cientos de metros (se descartan las abejas con más de 1 km). El mapa usa `web/public/data/fauna.json`, que sale
del mismo script.

| Columna | Tipo | Qué es |
|---|---|---|
| `h3_padre` | str | barrio H3 resolución 7 |
| `aves_registros` | int | registros de aves (clase Aves) en el barrio |
| `aves_especies` | int | especies de aves distintas |
| `aves_top` | str | las 5 especies con más registros, separadas por «; » (nombre común si GBIF lo tiene) |
| `abejas_nativas` | int | registros de abejas (Apidae, Megachilidae, Halictidae, Andrenidae, Colletidae) sin las exóticas |
| `abejas_especies` | int | especies (o géneros) de abejas nativas distintas |
| `abejas_top` | str | las 3 abejas nativas con más registros, separadas por «; » |
| `abejas_exoticas` | int | registros de abeja de miel (*Apis mellifera*) y abejorro europeo (*Bombus terrestris*) |
| `consultado` | str | fecha de la consulta a GBIF, AAAA-MM-DD |

Un registro dice que alguien vio la especie ahí; no haber registro no significa que no esté, y hay más
observadores en parques y barrios acomodados. Por eso es una capa para mostrar y validar, no un peso del índice.

## Cómo regenerar

```bash
python -m verdeh3.pipeline ...           # grilla, OSM, NDVI, LST y población (ver README)
python -m verdeh3.marcar_gs              # elevación y marcas
python -m verdeh3.landsat                # lst_c con la última escena de verano (dic–feb) y lst_fecha
python -m verdeh3.landsat --modo ultima  # lst_c_ultima con la escena más reciente disponible
python -m verdeh3.worldcover             # árboles, pasto y construido
python -m verdeh3.arboles                # árboles estimados con la altura de copa de Meta (baja 332 MB)
python -m verdeh3.modelo_copa            # modelo propio de copa: entrena con Meta 2019 y predice 2026 (~3 min)
python -m verdeh3.impact                 # % de árboles Impact Observatory, año más reciente y 2021
python -m verdeh3.censo                  # población Censo 2024 (zip del INE descomprimido en cache/censo2024/)
python -m verdeh3.contrato               # los tres parquet y data/cifras_pitch.json
```
