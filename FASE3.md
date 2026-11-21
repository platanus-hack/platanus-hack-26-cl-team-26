# MagneSense · Fase 3: agente, gestos y acciones

La persona inventa sus propios gestos y decide qué hace cada uno, conversando con un agente (Claude) en el panel.

## Quién hace qué

| Paso | Dónde |
|---|---|
| Poner el imán, calibrar y grabar 3 ejemplos por gesto | App del teléfono o panel (sin agente) |
| Crear el detector y revisar su calidad | Agente |
| Probarlo en vivo ("haz el gesto 3 veces") | Agente |
| Conectar cada gesto a una acción, o crear acciones nuevas | Agente |
| Aprobar acciones `http` o `comando` | Una persona, en el panel |

## Aprendizaje automático de movimientos

El usuario solo pide algo ("girar hacia la derecha prende y apaga la luz") y graba el movimiento varias veces. El servidor (`analysis.py`) decide cómo reconocerlo:

1. **Revisa cada ejemplo.** Mira el pico contra el ruido, si quedó cortado al final de la ventana y si se movió el celular. Descarta los que no se vieron. Si se vio menos de la mitad, **no entrena** y explica qué hacer (acercar el imán a 2–3 cm del sensor, dejar el celular fijo, empezar antes).
2. **Elige el modelo:**
   - **dirección:** el gesto empuja siempre hacia un lado distinto de los demás movimientos grabados.
   - **patrón** (`trajectory.py`): compara la forma completa del movimiento contra **todos** los movimientos grabados. Sirve cuando dos movimientos empujan parecido pero en otro orden: girar a un lado u otro, o barrer de izquierda a derecha o al revés.
3. **Hacia la app, todo es un detector `event` normal.** La app Android no necesita cambios: manda `/train` con `type: "event"` y el servidor elige.

El agente recibe este análisis (en el modo de la app, en el campo `analisis`). Así explica en palabras simples qué vio el sensor y propone regrabar en vez de crear un detector que no sirve.

- `GET /examples/analysis`: el diagnóstico completo.
- Panel, sección **Diagnóstico de ejemplos**: el pico de cada ejemplo (verde si se vio, rojo si no), el modelo elegido y los problemas.
- Panel, sección **Depuración del celular**: los eventos que manda la app Android por `POST /app-event`, con señal y coseno.

## Acciones

Cada acción es una pieza combinable. Un detector puede tener varias reglas, por ejemplo corto → "Tengo sed", largo → pausar música y doble → apagar la TV.

| Tipo | Qué hace | ¿Requiere aprobación? |
|---|---|---|
| `luz` | Prende, apaga o alterna la lámpara o el enchufe (`ACTUATOR_ON_URL` / `ACTUATOR_OFF_URL`) | No |
| `decir` | Dice una frase por el parlante | No |
| `sonido` | Reproduce un archivo de `sounds/` | No |
| `media` | Pausa, siguiente, anterior, volumen y silencio en el notebook (Spotify, YouTube, VLC...) | No |
| `avisar` | Mensaje al cuidador. El destino lo configura el equipo, no el agente | No |
| `http` | Llama a una URL: TV, Home Assistant, enchufes con API | **Sí** |
| `comando` | Ejecuta un programa: `adb` para Android TV, `cec-client` para HDMI-CEC, `catt` para Chromecast | **Sí** |

Vienen integradas `luz_*`, `musica_*` y `volumen_*`. Las acciones y reglas se guardan en `data/acciones.json` y se mantienen al reiniciar.

Los gestos que se pueden conectar son:
- **Evento:** `inicio` (el más rápido), `corto`, `largo` (más de 0,8 s), `doble` y `fin`.
- **Estado:** `estado:<etiqueta>`.
- **Ritmo:** `pausa` y `reanuda`.

## Configuración

```
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...         # sin esto el agente aparece "no disponible" y el panel sigue funcionando
export NTFY_TOPIC=un-nombre-dificil  # aviso al cuidador con la app ntfy (sin cuenta)
# o bien TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID
python server.py
```

- **Música** en Linux: necesita `playerctl` y `wpctl`.
- **Modelo:** `claude-opus-5-5` con esfuerzo bajo, para responder rápido. Se cambia con `AGENT_MODEL` y `AGENT_EFFORT`.

## Plan B

Sin internet o sin clave, los detectores, las reglas ya creadas y los botones del panel siguen funcionando. Solo se pierde la conversación.

## Pruebas

```
python -m pytest -q
```

`test_agent.py` reemplaza el modelo por respuestas guionadas, así que no llama a la API ni gasta. Valida el motor de acciones, las aprobaciones, la prueba en vivo y el recorrido completo: grabar ejemplos → crear detector → conectar → un gesto ejecuta la acción. La conversación real con Claude no está probada por estas pruebas.
