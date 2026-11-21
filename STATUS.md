# STATUS.md

Cada hora, tres líneas por persona: Hecho / Siguiente / Bloqueado o cambios al contrato.

## Rol 1 · Base satelital y optimizador
- Hecho:
- Siguiente:
- Bloqueado / contrato:

## Rol 2 · Sensores en vivo
- Hecho: rama-vivo, CONTRATO.md, tests/test_contrato.py, data/live_h3_mock.parquet. web_sensors.py lee DMC + sensor.community cada 5 min, graba en data/grabacion/ y escribe data/web_sensors.json.
- Siguiente: token de la DMC; control de calidad e índice de calor.
- Bloqueado: sensor.community tiene 1 solo sensor con temperatura en todo Chile (Las Condes), así que el plan B «solo sensor.community» no alcanza. La DMC pide usuario y token (registro en climatologia.meteochile.gob.cl) y tiene unas 5 estaciones urbanas en Santiago. SINCA no publica temperatura en tiempo real. Con pocos sensores, la interpolación por hexágono va a ser gruesa: hay que conversarlo en el Sync 1.
- Contrato: el parquet actual de Rol 1 (datos/salida_h3/santiago_h3.parquet) usa `h3` y `lng`, no `h3_index` y `lon`, y no trae arbol_pct, pasto_pct, construido_pct, social ni es_parque. Falta acordar si se adapta al contrato o se cambia el contrato.

## Rol 3 · Interfaz y pitch
- Hecho:
- Siguiente:
- Bloqueado / contrato:
