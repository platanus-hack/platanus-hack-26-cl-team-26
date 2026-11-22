# Notas para el pitch · Viridis

Todas las cifras salen de archivos del repo y se pueden regenerar. Al lado de cada una va su fuente.

## Nuestro modelo de copa de árboles

**Frase corta:** entrenamos un modelo propio que ve la copa de los árboles de Santiago en imágenes
satelitales gratuitas de 2026 y sigue al mapa de referencia de Meta mejor que el mapa global de la ESA.

- **Qué hace:** para cada píxel de 10 m de Sentinel-2 predice qué % está cubierto por copa de árbol
  (vegetación de 3 m o más). Por hexágono eso da el % de copa, que es el término de árboles del índice.
- **Con qué aprendió:** el mapa de altura de copa de Meta y WRI (1 m, imágenes de octubre y noviembre de
  2019; Tolan et al. 2024) como respuesta correcta, y una imagen Sentinel-2 del 8 de febrero de 2020.
- **Con qué predice:** la imagen Sentinel-2 del 6 de febrero de 2026. Se actualiza con cualquier pasada
  nueva de verano, en unos 3 minutos (`python -m verdeh3.modelo_copa`).
- **Tipo de modelo:** gradient boosting (scikit-learn), 15 variables: 10 bandas, 3 índices de vegetación y
  2 de textura y vecindad. Entrenado con 600.000 píxeles. Queda en `datos/modelo_copa.joblib`.

### Qué tan bien funciona

Validación en comunas que el modelo nunca vio al entrenar (5 grupos de comunas, 10.720 hexágonos urbanos
de las 34 comunas), comparando contra Meta 2019. Fuente: `data/modelo_copa.json`.

| Por hexágono | Correlación con Meta | Error medio (puntos de % de copa) |
|---|---|---|
| Nuestro modelo | 0,92 | 1,8 |
| ESA WorldCover 2021 | 0,84 | 7,1 |

- En Providencia la correlación es 0,95 y en Cerro Navia 0,78 (WorldCover: 0,88 y 0,68).
- Sin sesgo en promedio: copa urbana media de 6,08% según el modelo contra 6,04% según Meta.

### Lo que NO hay que decir

- **No ubica árboles individuales.** Píxel por píxel la correlación es 0,70; sirve por cuadra.
- **El mapa de 2026 no está comprobado contra una medición de 2026**, porque no existe. Contra Meta 2019
  correlaciona 0,84. No afirmar que una cuadra ganó o perdió árboles.
- **Se queda corto donde hay muchos árboles:** en Providencia da 13,0% para 2026, contra 15,6% de Meta 2019.
- **No decir grados de enfriamiento:** no tenemos un coeficiente publicado que citar.

## Otras cifras verificadas

Fuente: `data/cifras_pitch.json`, `data/santiago_h3_gs.parquet` y `datos/salida_h3_gs/santiago_h3.parquet`.

- **Brecha entre comunas:** Cerro Navia tiene 38,9 °C de temperatura de suelo y 5,0% de copa; Providencia,
  35,1 °C y 13,0% (Landsat del 19 de febrero de 2026 y nuestro modelo).
- **Corredor de 3 km en Cerro Navia:** cubre 11.908 personas, contra 8.261 de un corredor al azar del mismo
  largo (Censo 2024).
- **Árboles por habitante** (árboles estimados con el mapa de Meta 2019 y Censo 2024, solo zona urbana bajo
  900 m, sin cerros): Lo Espejo 0,07, San Miguel 0,10, San Ramón 0,11 y Pedro Aguirre Cerda 0,11; Vitacura
  2,5. Casi 40 veces de diferencia entre Lo Espejo y Vitacura. Si se cuentan los cerros, Vitacura sube a
  5,2 y Lo Barnechea a 25: esas cifras no sirven para comparar barrios.
- **Pasto no es sombra:** en los 10.720 hexágonos urbanos, donde hay más pasto el suelo está más caliente
  (r = +0,46) y donde hay más copa de árboles, más fresco (r = −0,50 con nuestro modelo; −0,44 con
  WorldCover). Temperatura de la escena Landsat del 19 de febrero de 2026; pasto de WorldCover 2021.
- **Verde que no da sombra:** 330 hexágonos del Gran Santiago se ven verdes en el satélite (NDVI ≥ 0,3) pero
  tienen menos de 5% de copa; son el 9,3% de los hexágonos verdes. Sobre todo en Maipú, San Bernardo y Pudahuel.
- **Impact Observatory 2023 no sirve para árboles urbanos:** marca 0% de árboles en Cerro Navia y 1,6% en
  Providencia. Por eso no lo usamos.

## Fuentes para citar

- Temperatura: Landsat 8/9 Collection 2 Level 2 (USGS), vía Microsoft Planetary Computer.
- Imágenes del modelo: Sentinel-2 L2A (ESA/Copernicus), vía Planetary Computer.
- Altura de copa: Tolan et al. (2024), Remote Sensing of Environment 300, Meta y World Resources Institute.
- Cobertura de suelo: ESA WorldCover 2021 v200 (Zanaga et al. 2022).
- Población: Censo de Población y Vivienda 2024, INE, a nivel de manzana.
- Parques, colegios, salud, metro y paraderos: OpenStreetMap.
