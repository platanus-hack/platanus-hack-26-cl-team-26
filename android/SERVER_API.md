# Contrato app ↔ server.py

Qué usa la app Android de `server.py` y qué falta construir en el servidor.
La app pone la URL base en **Ajustes → Servidor** (p. ej. `http://192.168.1.20:8000`).

## Lo que ya existe y la app usa

| Uso en la app | Endpoint | Notas |
|---|---|---|
| Telemetría | `POST /data` | Formato Sensor Logger, cada ~100 ms. Incluye `magnetometeruncalibrated` y **`gyroscope`**. |
| Eventos de la app al panel | `POST /app-event` | `{type, text, time, signal?, cosine?}` |
| Estado en vivo y eventos | `WS /ws` | Mensajes `state` y `data`. Lee `phase2`, `recording`, `examples` y `events2`. |
| Grabar un ejemplo | `POST /record/start {label}` → `POST /record/stop` | Gesto breve: la app detiene la grabación sola a los 2 s. Posición: cuando el cuidador toca "Listo". |
| Borrar ejemplos | `POST /examples/clear {label}` | |
| Crear un detector | `POST /train` | La app **siempre** manda `"action":"none"`: el servidor solo detecta y la app ejecuta la acción (enchufe, voz, historial). |
| Borrar un detector | `POST /detectors/remove {name}` | |

### Cuándo dispara un gesto (la app lo calcula)
La app copia la regla de `Bank._action` (`detectors.py`) y usa el `trigger` que guarda el servidor:
- `event`: `kind == trigger`, o `trigger == "any"` y `kind == "start"`.
- `rhythm`: `kind == "pause"`.
- `state`: `kind == "state"` y `state == trigger`.

Si cambian esa regla en el servidor, avisen para ajustar `gestures/GestureMatcher.kt`.

## Lo que falta: `POST /agent` (asistente con Claude)

La tarjeta **Asistente** de la pestaña Gestos envía el pedido del cuidador en lenguaje natural.
Mientras el endpoint no exista (404), la app muestra "El asistente todavía no está conectado".

### Petición
```json
{
  "text": "cuando mueva el dedo a la izquierda, prende la luz",
  "context": {
    "devices":   [{"id": "luz", "name": "Luz"}, {"id": "ventilador", "name": "Ventilador"}],
    "detectors": [{"name": "derecha", "type": "event", "trigger": "any"}],
    "examples":  {"derecha": 5},
    "bindings":  {"derecha": "ventilador"}
  }
}
```

### Respuesta
```json
{
  "reply": "Perfecto. Primero graba 5 veces el movimiento hacia la izquierda.",
  "steps": [
    {"type": "record", "label": "izquierda", "count": 5, "detector_type": "event"},
    {"type": "train",  "detector_type": "event", "name": "izquierda", "label": "izquierda", "trigger": "any"},
    {"type": "bind",   "detector": "izquierda", "device": "luz"}
  ]
}
```

- `reply` se muestra y se lee en voz alta (español, frases cortas).
- Cada paso aparece con un botón **Hacer**: la app no ejecuta nada sin que el cuidador lo toque.
  - `record`: abre el asistente de grabación con ese nombre y tipo.
  - `train`: llama a `/train` con esos campos (y `action` = `none`). Para `state`, usar `"labels": [...]`, y `trigger` es la posición que activa.
  - `bind`: el `device` es un `id` de `context.devices`, o `"scan"` (abre el escaneo) o `"none"`.
- Un paso de otro tipo se muestra como "no soportado" y no se ejecuta.
- La app espera hasta 30 s. Si hay un error, conviene devolver `{"error": "texto"}` con código 4xx/5xx.

## Sugerencias para el servidor
- **Guardar los detectores en disco.** Hoy viven en memoria: si `server.py` se reinicia, la app avisa "El servidor olvidó este gesto".
- Agregar pruebas de `/record/*`, `/train` y `/detectors` en `test_server.py`.
- Un detector entrenado con 3 grabaciones sin movimiento obtuvo consistencia 1,00 y se disparó solo 4 veces en un minuto. Convendría rechazar ejemplos cuya señal no supere el ruido.
