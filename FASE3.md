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

### Contraejemplos "otros" y giro

- **Contraejemplos:** la etiqueta **`otros`** son movimientos que **no** deben activar nada: acercar el imán, moverlo recto, tocar el celular. Nunca se entrenan como gesto (`/train` los rechaza). El detector de patrón los usa para comparar: si un movimiento se parece más a "otros" que al gesto, no se activa. Cuando hay contraejemplos, el servidor usa siempre *patrón*, porque el modelo de dirección no puede aprender de ellos. El agente pide grabar 4 contraejemplos automáticamente si faltan.
- **Rasgo de giro:** además de la forma, el detector mide **cuánto gira el vector del campo** (eje × ángulo). Girar el imán lo hace rotar; acercarlo o moverlo recto, mucho menos.
- **Ventana fija:** se decide en una ventana desde el inicio del movimiento, aprendida de los ejemplos (0,4 a 1,6 s). La misma ventana se usa al entrenar y en vivo, así que funciona aunque el imán no vuelva a su lugar. Si queda desplazado, esa posición pasa a ser el reposo.
- **Frecuencia por ejemplo:** cada ejemplo guarda su propia frecuencia de muestreo, para que la ventana no se distorsione si el reloj del teléfono salta.
- **Revisiones nuevas del análisis:**
  - si el imán no volvió a su lugar (↩ en el panel),
  - si la fuerza cambia más de 4 veces entre intentos (distinta distancia),
  - el giro de cada ejemplo (↻ en el panel).

**Medir con sesiones reales:**
```
python replay_learning.py data/session_X.csv
python replay_learning.py data/session_X.csv --otros derecha
```
El primero reproduce la sesión por el pipeline del servidor, entrena como `/train` y cuenta las activaciones dentro y fuera de cada grabación. El segundo trata una etiqueta grabada como "otros".

El agente recibe este análisis (en el modo de la app, en el campo `analisis`). Así explica en palabras simples qué vio el sensor y propone regrabar en vez de crear un detector que no sirve.

- `GET /examples/analysis`: el diagnóstico completo.
- Panel, sección **Diagnóstico de ejemplos**: el pico de cada ejemplo (verde si se vio, rojo si no), el modelo elegido y los problemas.
- Panel, sección **Depuración del celular**: los eventos que manda la app Android por `POST /app-event`, con señal y coseno.

## Posición 3D del imán (`localize.py`)

El panel tiene una sección **Posición 3D del imán** para ver si el sensor está midiendo bien. Modela el imán como un dipolo y calcula su posición (x, y, z en cm) respecto al magnetómetro.

**Ejes del teléfono:** x a la derecha, y hacia arriba de la pantalla, z saliendo de la pantalla.

1. **Medir sin imán:** con el imán a más de 30 cm. Guarda el campo de la Tierra y del teléfono, y el ruido.
2. **Calibrar imán:** pon el imán **justo sobre el punto del sensor** (prueba 1 del informe), a la distancia indicada (3 cm por defecto), **mirando como lo vas a usar**. Se mide su fuerza y su orientación.
3. **Seguimiento en vivo:** vista 3D (arrastrar para girar, Shift + rueda para acercar) y coordenadas.

**Ajuste del modelo:** qué parte del campo medido explica el modelo en la posición hallada. Con 3 mediciones y 3 incógnitas casi siempre calza, así que **no detecta si el imán cambió de orientación**: para eso hay que comparar con puntos conocidos. Si baja, puede ser que:
- el imán se inclinó respecto a la calibración (con un solo sensor no se puede calcular a la vez la posición y la orientación),
- está a menos de ~1,5 cm (ya no se comporta como dipolo, o satura el sensor),
- hay metal cerca.

**Limitaciones físicas:**
- El imán y su reflejo a través del sensor (izquierda↔derecha, arriba↔abajo) dan exactamente la misma lectura. Se elige la solución más cercana a la posición anterior, porque el imán se mueve de forma continua. Al empezar se elige el lado de la pantalla. Elegir siempre z > 0 hacía que el imán al lado del celular, a la altura de la mesa, apareciera al lado contrario.
- Girar el imán sobre su propio eje, como un trompo, no se ve.

**Precisión con un imán simulado:** menos de 1 mm. En la realidad la limita sobre todo que el imán se incline: ~1 mm de error por cada 5° de inclinación no prevista.

Endpoints: `POST /tracker/base`, `POST /tracker/calibrate {"dist_cm": 3}`, `POST /tracker/reset`, `GET /tracker`. Cada mensaje `data` de `/ws` trae `tracker`.

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
