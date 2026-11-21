# STATUS.md

Cada hora, tres líneas por persona: Hecho / Siguiente / Bloqueado o cambios al contrato.

## Rol 1 · Base satelital y optimizador
- Hecho:
- Siguiente:
- Bloqueado / contrato:

## Rol 2 · Sensores en vivo
- Hecho: rama-vivo creada; CONTRATO.md, tests/test_contrato.py y data/live_h3_mock.parquet (30 hexágonos reales de Providencia y Cerro Navia, valores inventados).
- Siguiente: registro en la API de la Dirección Meteorológica; web_sensors.py (DMC + sensor.community cada 5 min, grabando en data/grabacion/).
- Bloqueado / contrato: el parquet actual de Rol 1 (datos/salida_h3/santiago_h3.parquet) usa `h3` y `lng`, no `h3_index` y `lon`, y no trae arbol_pct, pasto_pct, construido_pct, social ni es_parque. Falta acordar si se adapta al contrato o se cambia el contrato.

## Rol 3 · Interfaz y pitch
- Hecho:
- Siguiente:
- Bloqueado / contrato:
