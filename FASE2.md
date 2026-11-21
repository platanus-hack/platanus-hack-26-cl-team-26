# MagneSense · Fase 2: detectores

`server.py` sigue funcionando igual que en la fase 1. La fase 2 agrega, en `detectors.py`:

| Detector | Qué detecta | Ejemplos |
|---|---|---|
| **Evento** | Un gesto puntual. Lo clasifica en corto, largo o doble. | contracción, toque, ceja |
| **Ritmo** | Algo periódico: mide la frecuencia y avisa si se detiene. | respiración, temblor |
| **Estado** | En qué posición está algo. | puerta abierta o cerrada, dedo estirado o recogido |

- **Dirección aprendida.** Con 3 ejemplos aprende hacia dónde empuja el imán el campo. Los cambios en otra dirección no cuentan, como un notebook que se mueve o unas llaves.
- **Línea base adaptativa.** En reposo sigue las derivas lentas. Lo que cambia fuera de la dirección del gesto se absorbe más rápido.
- **Giroscopio.** Si Sensor Logger envía `gyroscope`:
  - Los giros lentos del teléfono se compensan, porque el campo de la Tierra rota con el teléfono.
  - Si el teléfono gira rápido (más de unos 14°/s), la detección se pausa. Cuando se queda quieto, la posición nueva pasa a ser el reposo.
  - Así, mover el teléfono no se confunde con mover el imán.

## Cómo usarlo (panel, sección "Fase 2")

1. Activa en Sensor Logger **Magnetometer** y **Gyroscope**.
2. Escribe una etiqueta, por ejemplo `contraccion`. Aprieta **Grabar ejemplo**, haz el gesto y vuelve a apretar. Repite 3 veces.
3. Aprieta **Crear detector de evento**. El panel muestra cuánto se parecen los ejemplos: sobre 0.8 está bien, y bajo eso conviene regrabarlos.
4. Para estados, graba cada posición con su etiqueta (`abierta`, `cerrada`) y aprieta **Crear detector de estado**.
5. Para ritmo, elige la banda (respiración o temblor) y aprieta **Crear detector de ritmo**. No necesita ejemplos.

Cuando hay detectores de fase 2, ellos manejan la lámpara o el enchufe. Si quitas todos, vuelve a manejarla el detector de la fase 1.

## Medir aciertos con grabaciones reales

Todo queda en `data/session_*.csv`. La columna `label` viene de los ejemplos grabados.

```
python evaluate.py data/session_X.csv                       # que etiquetas hay
python evaluate.py data/session_X.csv --event contraccion   # aprende con 3 y mide el resto
python evaluate.py data/session_X.csv --state --labels abierta cerrada
python evaluate.py data/session_X.csv --rhythm respira --per-min 12
```

El detector de eventos se compara contra el de la fase 1 (solo magnitud). La comparación muestra aciertos, falsas alarmas y latencia.

## Qué grabar (una sesión por caso, teléfono fijo y el imán cerca del sensor)

| Caso | Grabar |
|---|---|
| Gesto | 10 veces el gesto con la etiqueta `contraccion`. Entre gestos, deja 3 s en reposo y haz 3 movimientos que NO deben contar (rascarse, mover el notebook), sin etiqueta. |
| Estado | 3 tramos de 5 s de cada posición, alternados (`abierta`, `cerrada`, `abierta`...). |
| Respiración | 60 s respirando normal con la etiqueta `respira`, contando las respiraciones a mano. Luego 15 s aguantando la respiración con la etiqueta `pausa`. |
| Teléfono movido | Sin imán, gira y mueve el teléfono unos segundos. No debe disparar nada. |

## Pruebas

```
python -m pytest -q        # test_server.py (fase 1) y test_detectors.py (fase 2)
```

Las pruebas usan datos de prueba generados por el código, solo para validar la lógica. Los aciertos reales salen de `evaluate.py` sobre grabaciones reales.
