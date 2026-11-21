# CONTRATO.md · VerdeH3

> Regla para todas las IA: antes de escribir código, lee CONTRATO.md. Nunca cambies nombres de archivos,
> columnas ni firmas que estén aquí. Si crees que hay que cambiarlo, detente y avisa.
>
> Este archivo solo se cambia con acuerdo de los tres roles. `tests/test_contrato.py` lo verifica.

## Ramas y dueños

| Rol | Rama | Archivos propios |
|-----|------|------------------|
| Rol 1 · Base satelital, índices fijos y optimizador | `rama-datos` | build_h3_dataset.py, optimizer.py, data/santiago_h3.parquet |
| Rol 2 · Sensores en vivo | `rama-vivo` | web_sensors.py, interpolate.py, alerts.py, data/live_h3.parquet, data/web_sensors.json, data/grabacion/ |
| Rol 3 · Interfaz y pitch | `rama-ui` | app.py, assets/, presentación |
| Los tres | — | CONTRATO.md, tests/, README.md, STATUS.md |

## Archivos compartidos

### `data/santiago_h3.parquet` (y `data/santiago_h3_mock.parquet`)
Escribe: Rol 1 · Leen: Roles 2 y 3

| Columna | Tipo | Notas |
|---------|------|-------|
| h3_index | str | resolución 9 |
| comuna | str | |
| lat, lon | float | centroide |
| lst_c | float | °C, Landsat |
| ndvi | float | 0 a 1 |
| arbol_pct | float | 0 a 100, WorldCover clase 10 |
| pasto_pct | float | 0 a 100, clase 30 |
| construido_pct | float | 0 a 100, clase 50 |
| poblacion | int | |
| social | float | 0 a 1: colegios, salud, metro y paraderos cercanos |
| es_parque | bool | |

### `data/live_h3.parquet` (y `data/live_h3_mock.parquet`), cada 5 min
Escribe: Rol 2 · Leen: Roles 1 y 3

| Columna | Tipo | Notas |
|---------|------|-------|
| h3_index | str | resolución 9 |
| temp_aire_c | float | °C, interpolada |
| humedad_pct | float | 0 a 100 |
| indice_calor_c | float | °C, sensación térmica |
| uv | float | índice |
| anomalia_c | float | °C sobre la estación oficial más cercana |
| n_sensores | int | sensores a menos de 2 km |
| alerta | bool | |
| timestamp | str | ISO-8601 |

### `data/web_sensors.json`, cada 5 min
Escribe: Rol 2 · Lee: Rol 3

Lista de lecturas crudas válidas:

```json
[{"source": "DMC_..." | "SC_...", "lat": float, "lon": float, "h3_index": str,
  "temp_c": float, "humedad_pct": float, "timestamp": "ISO-8601"}]
```

### `optimizer.solve_corridor()`
Escribe: Rol 1 · Leen: Roles 2 y 3

```python
# optimizer.py (Rol 1)
def solve_corridor(df, budget_km=3.0, w_calor=0.4, w_arbol=0.4, w_personas=0.2, live=None) -> dict:
    """
    df: santiago_h3.parquet. live: live_h3.parquet (si viene, el calor usa indice_calor_c en vivo
    combinado con lst_c; si no, solo lst_c).
    Devuelve {"hexes": [h3_index, ...], "length_km": float, "urgencia_cubierta": float,
              "urgencia_azar": float, "personas_cubiertas": int}
    """

# Versión provisoria para Roles 2 y 3 mientras Rol 1 termina:
#   top = df.nlargest(10, "lst_c")
#   return {"hexes": top.h3_index.tolist(), "length_km": 3.0, "urgencia_cubierta": 0,
#           "urgencia_azar": 0, "personas_cubiertas": 0}
```

## Fórmula de urgencia (cada término normalizado de 0 a 1)

```
calor    = 0.6 * lst_c_norm + 0.4 * indice_calor_norm   # sin datos en vivo: solo lst_c_norm
falta    = 1 - arbol_pct/100                            # árboles, no NDVI: el pasto no da sombra
personas = 0.7 * poblacion_norm + 0.3 * social
U = w_calor*calor + w_arbol*falta + w_personas*personas
# Dijkstra: costo de entrar a un hexágono = 1 / (0.05 + U); parques cuestan 0
```
