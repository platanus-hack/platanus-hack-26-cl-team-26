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
| `lst_c` | float | temperatura superficial, °C | Landsat 8/9 C2 L2, verano 2025-26 |
| `ndvi` | float 0–1 | vegetación | Sentinel-2 L2A (B08, B04) |
| `arbol_pct` | float 0–100 | % del hexágono con árboles | ESA WorldCover 2021 v200, clase 10 |
| `pasto_pct` | float 0–100 | % con pastizal | ESA WorldCover, clase 30 |
| `construido_pct` | float 0–100 | % construido | ESA WorldCover, clase 50 |
| `poblacion` | int | personas en el hexágono | WorldPop 2020 constrained (el Censo 2024 por manzana aún no está integrado) |
| `social` | float 0–1 | cercanía a colegios, salud, metro y paraderos: promedio de max(0, 1 − distancia/1 km) | OpenStreetMap |
| `es_parque` | bool | toca un parque consolidado (≥ 5.000 m²) y ≥ 25% del hexágono es área verde | OpenStreetMap |

Columnas extra (pueden ignorarse): `urgencia` y `en_corredor`, calculadas con los pesos por defecto y 3 km.

## `optimizer.py` (Rol 1)

```python
solve_corridor(df, budget_km=3.0, w_calor=0.4, w_arbol=0.4, w_personas=0.2, live=None, terreno=None) -> dict
```

- `live`: el `data/live_h3.parquet` del Rol 2 (ver abajo). Se une por `h3_padre` sin perder cuadras y se
  usa `temp_aire_c` solo donde `confianza` es "alta" o "media".
- Devuelve `hexes` (list[str]), `length_km`, `urgencia_cubierta` (U media del corredor),
  `urgencia_azar` (U media de corredores al azar del mismo largo) y `personas_cubiertas` (int).
  También trae `personas_azar`, `tramos` (cada tramo es una lista de hexágonos, de parque a parque) y
  `urgencia` (Serie por hexágono, para colorear el mapa).
- `terreno` (opcional): el `data/terreno_h3.parquet` de la captura en terreno (ver abajo). Donde hay fotos,
  `arbol_pct` pasa a ser el promedio entre satélite y terreno, y los hexágonos con `viabilidad_terreno < 0,2`
  que no son parque salen del grafo. Devuelve además `verificados` (hexágonos del corredor con foto).
  Sin `terreno` el resultado es idéntico.

Fórmula, con cada término normalizado de 0 a 1 (min-max entre los percentiles 2 y 98):

```
calor    = 0,6·lst_c_norm + 0,4·vivo_norm     (vivo = temp_aire_c del barrio, confianza alta o media)
           sin dato en vivo en esa cuadra, o con menos de dos barrios con dato: calor = lst_c_norm
falta    = 1 − arbol_pct/100
personas = 0,7·poblacion_norm + 0,3·social
U        = (w_calor·calor + w_arbol·falta + w_personas·personas) / (w_calor + w_arbol + w_personas)
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

Una fila por barrio (H3 resolución 7), no por cuadra.

| Columna | Tipo | Qué es |
|---|---|---|
| `h3_padre` | str | barrio H3 resolución 7 |
| `temp_aire_c` | float | temperatura del aire, °C |
| `humedad_pct` | float | humedad relativa, % |
| `indice_calor_c` | float | índice de calor, °C (informativo) |
| `anomalia_c` | float | diferencia contra lo esperable, °C |
| `n_sensores` | int | sensores que aportan al barrio |
| `dist_min_km` | float | distancia al sensor más cercano |
| `confianza` | str | "alta", "media", "baja" o "sin dato" |
| `medido_en` | timestamp | hora de la medición |
| `alerta` | bool | opcional |

## `data/terreno_h3.parquet` (captura en terreno)

Sección nueva y aditiva: no cambia las tablas de arriba. Avisar a Rol 3 (mapa) y a Corredores (v4: alimenta
`V_c` y la marca «verificado en terreno»). Lo escribe `terreno/servidor.py` cada vez que llega una foto desde
el teléfono; las capturas crudas quedan en `data/terreno/capturas.jsonl`. Una fila por hexágono res 9 con fotos.

| Columna | Tipo | Qué es |
|---|---|---|
| `h3_index` | str | hexágono H3 res 9 de la posición GPS del teléfono |
| `n_capturas` | int | fotos en ese hexágono |
| `arbol_pct_terreno` | float 0–100 | % de árboles en la vista (Claude; sin Claude, el % de verde de la foto) |
| `verde_pct_terreno` | float 0–100 | % de píxeles con vegetación (índice ExG, siempre disponible) |
| `plantable` | float 0–1 | espacio para plantar: ninguno 0, poco 0,33, medio 0,67, mucho 1. NaN si solo hubo índice |
| `viabilidad_terreno` | float 0–1 | `plantable − 0,15 × obstáculos distintos` (máx. 3), recortado. NaN si no hay `plantable` |
| `obstaculos` | str | obstáculos distintos, separados por «; » |
| `fuente` | str | "claude" si alguna foto se analizó con Claude, si no "indice_verde" |
| `ultima_captura` | timestamp UTC | hora de la última foto |

Una foto de calle ve solo parte del hexágono: complementa al satélite, no lo reemplaza.

## Cómo regenerar

```bash
python -m verdeh3.pipeline ...           # grilla, OSM, NDVI, LST y población (ver README)
python -m verdeh3.marcar_gs              # elevación y marcas
python -m verdeh3.worldcover             # árboles, pasto y construido
python -m verdeh3.contrato               # los tres parquet y data/cifras_pitch.json
```
