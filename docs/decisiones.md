# Decisiones de diseño

Cada decisión con la alternativa que descartamos y la evidencia. Las cifras salen de archivos del repo y se
reproducen con los comandos del [README](../README.md#resultados); el detalle de columnas está en
[CONTRATO.md](../CONTRATO.md).

## 1. Una grilla de hexágonos H3, no manzanas

- **Elegimos** H3 resolución 9 (unos 0,1 km², «una cuadra») para el corredor, y resolución 7 (barrio) para el
  aire y la fauna.
- **Descartamos** las manzanas del Censo, de formas y tamaños muy distintos, y una grilla cuadrada, donde los
  vecinos en diagonal están más lejos que los de al lado.
- **Por qué:** todas las celdas tienen la misma área y seis vecinos a la misma distancia, así que el grafo del
  corredor y las comparaciones entre zonas son justos. El aire y la fauna van por barrio porque las estaciones y
  los registros tienen un margen de cientos de metros (las abejas con más de 1 km se descartan).
- **Cómo cruzamos el Censo:** cada manzana reparte sus personas entre las cuadras según el área que comparten
  (`verdeh3/censo.py`).

## 2. El corredor es un camino de menor costo, no un ranking de cuadras

- **Descartamos** marcar las N cuadras más urgentes: quedan manchas sueltas que no conectan ninguna isla.
- **Elegimos** un grafo donde entrar a una cuadra cuesta 1 / (0,05 + urgencia) y los parques cuestan 0. Un
  Dijkstra con todos los parques como origen da el camino más barato entre cada par de parques vecinos
  (`optimizer.py`).
- **Por qué:** es el enfoque estándar de conectividad en ecología del paisaje (caminos de menor costo sobre una
  superficie de resistencia), aplicado a la ciudad y a las personas además de la fauna.

## 3. Una heurística rápida en vez del óptimo exacto

- **El problema exacto**, elegir un conjunto conexo de cuadras que maximice la urgencia cubierta sin pasarse de un
  largo, es NP-difícil (una variante del árbol de Steiner con premios).
- **Elegimos** una red continua codiciosa: parte de un tramo y le suma los tramos que se tocan con la red, los de
  mayor urgencia media primero, mientras quepan en el presupuesto. Prueba los 20 tramos más urgentes como punto
  de partida y se queda con la mejor red. Tarda unos 80 ms con las 34 comunas, así
  que los controles de la página responden al instante.
- **Costo:** no garantiza el óptimo. Por eso cada resultado se compara contra el azar (decisión 4).

## 4. Siempre contra una línea base al azar

- Sin una comparación, «el corredor cubre 11.908 personas» no dice nada.
- **Línea base:** 200 caminatas al azar con los mismos largos por tramo, que parten junto a un parque; se informa
  el promedio.
- **Resultado:** con 3 km, 44 % más personas que al azar entre Providencia y Cerro Navia, y 63 % más en las 34
  comunas (`data/cifras_pitch.json`).

## 5. Copa de árboles con un modelo propio, no NDVI ni WorldCover

- **El NDVI mide verde, no sombra.** En los 10.720 hexágonos urbanos, donde hay más pasto el suelo está más
  caliente (r = +0,46) y donde hay más copa, más fresco (r = −0,50). Hay 330 cuadras que se ven verdes desde el
  satélite (NDVI ≥ 0,3) y tienen menos de 5 % de copa.
- **ESA WorldCover 2021** sigue a la copa urbana con r = 0,84 y 7,1 puntos de error medio contra el mapa de Meta.
  El mapa de Meta y WRI (1 m) es el mejor, pero es de 2019.
- **Elegimos** un modelo propio (gradient boosting, 15 variables de Sentinel-2) entrenado con Meta 2019 que
  predice la copa de 2026. Validado en comunas que no vio al entrenar: r = 0,92 y 1,8 puntos de error medio
  (`data/modelo_copa.json`, `verdeh3/modelo_copa.py`).
- **Límite:** sirve por cuadra, no ubica árboles individuales.

## 6. Cada término de 0 a 1, robusto a extremos

- **Descartamos** el min-max simple: un par de cuadras extremas (un cerro, un estacionamiento) aplastan a todas
  las demás contra 0 o 1.
- **Elegimos** escalar entre los percentiles 2 y 98, y recortar.
- **El aire va en escala fija** de ±3 °C alrededor de la mediana, y solo si hay al menos 5 barrios con dato
  confiable: unas décimas de grado entre pocas estaciones no deben reordenar el corredor.

## 7. Pesos por omisión 35 / 35 / 20 / 10

- Calor, falta de árboles, personas y vulnerabilidad. Se pueden mover en la página y se reescalan para
  sumar 100 %.
- **Descartamos 40 / 40 / 10 / 10**, que hacía espacio para la vulnerabilidad quitándole peso a «personas»: el
  corredor de las 34 comunas se iba a cuadras industriales, con 1.436 personas contra 7.002 al azar.
- **Con 35 / 35 / 20 / 10** cubre 11.393 contra 7.002, y su gente es más vulnerable al calor que el promedio de
  Santiago (índice 0,52 contra 0,40, ponderado por personas).
- Las cuadras con menos de 50 personas que no son parque (industria, eriazo) no entran al grafo.

## 8. Vulnerabilidad: del Censo, y solo para personas

- **Qué mide:** sensibilidad (personas de 60 años o más, de 0 a 5 años y con discapacidad) y capacidad de
  adaptación (viviendas hacinadas e irrecuperables, años de escolaridad). El Censo no pregunta ingreso
  (`verdeh3/contrato.py`; explicación completa en la página `/fuentes`).
- **Solo para personas:** la resistencia de aves y abejas no la usa; un test comprueba que su corredor no cambia
  (`tests/test_vulnerabilidad.py`).
- **Santiago conectado no la usa** (`PESOS_RED` en `red_conectada.py`), para que sus cifras sigan siendo
  comparables con las del pitch.

## 9. Un criterio por especie

- **Aves:** resistencia según copa, pasto y construido, para buscar copa continua entre islas.
- **Abejas:** mini islas floridas, una cuadra por medio, para que el mismo presupuesto alcance el doble de
  distancia.
- **Varias especies:** promedio simple de prioridad y costo (`ecologia.py`).
- **La fauna de GBIF se muestra, pero no pesa en el índice.** Un registro dice que alguien vio la especie ahí; no
  haber registro no dice que no esté, y hay más observadores en parques y barrios acomodados. Pesarla premiaría a
  los barrios con más observadores.

## 10. Aire: la máxima de ayer de estaciones oficiales

- **Descartamos** la lectura del momento: depende de la hora a la que se abre la página (de noche toda la ciudad
  está fresca), y un plan de plantación no debería cambiar con eso. La máxima del día corresponde al calor de la
  tarde y se puede comparar entre días.
- **Solo estaciones oficiales** (DMC y SINCA): Sensor.Community no guarda el día, así que no deja calcular la
  máxima.
- **Calidad:** una estación entra solo si midió en al menos 3 de las 4 horas más calientes (14 a 18 h); con menos,
  su máxima podría quedar baja.
- **Operación:** GitHub Actions la calcula cada noche (`maximas.py`). SINCA bloquea las conexiones desde fuera de
  Chile, así que se suma después desde un PC en Chile (`scripts/systemd/`).

## 11. Un solo servicio

- El sitio (Next.js) se exporta a archivos estáticos que sirve el mismo servidor FastAPI: un enlace, un
  contenedor y sin configuración de CORS (`Dockerfile`).
- Cada navegador tiene su propia sesión en el servidor (área, pesos y especies), así varias personas usan la página
  a la vez sin pisarse.
- «Santiago conectado» se precalcula (`web/public/data/red.json`): la red de cada presupuesto son los primeros
  tramos de la de 100 km, así crece sin cambiar de lugar y el control responde sin calcular nada.

## 12. Reglas de fidelidad

- Nunca inventamos un dato del aire: viene de estaciones oficiales, es por barrio, y en la urgencia solo entra
  donde la confianza es alta o media.
- No prometemos grados de enfriamiento: no hay un coeficiente publicado para Santiago que podamos citar.
- El formato de los datos es un contrato con test (`CONTRATO.md`, `tests/test_contrato.py`), y los tests corren
  en cada push (`.github/workflows/tests.yml`).
