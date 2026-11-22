# Viridis · Pitch de 3 minutos y guion de demo
**Platanus Hack 26 · Track Physical World**

Todas las cifras de este guion salen de archivos del repo; al lado de cada una va su fuente. Las mismas cifras,
con más detalle y lo que no hay que decir, están en `NOTAS PITCH.md`.

---

## Estructura (180 segundos)

```
[0:00 - 0:30] El problema: la brecha de calor y de sombra dentro de Santiago
[0:30 - 1:00] Viridis: calor, copa, personas, aves y abejas, cuadra por cuadra, en las 34 comunas
[1:00 - 2:00] Demo en vivo: elegir dónde, ver la fauna registrada y trazar el corredor para personas o para aves y abejas
[2:00 - 2:40] Números: cuánta gente cubre el corredor frente a un trazado al azar
[2:40 - 3:00] Cierre: Santiago conectado, la red completa que une las islas verdes
```

---

### 0:00 – 0:30 · Donde se necesita el verde
* **Pantalla:** la portada y luego el corto «El viaje del picaflor» (parte solo; se puede dejar correr de fondo
  mientras se habla, o adelantarlo con la barra); después «Datos clave»
  con Providencia y Cerro Navia elegidas, para que la tabla muestre las dos comunas lado a lado.
* **Orador:**
  > *"El picaflor chico, el colibrí que más se ve en Santiago, quiere ir del Cerro Renca al San Cristóbal. En
  > línea recta tiene **16 cuadras seguidas sin un árbol** donde descansar. Los cerros y parques son islas, y
  > el cemento las separa. Santiago no es desigual solo en ingresos: también en sombra. La tarde del 19 de febrero de 2026, el suelo
  > de Cerro Navia estaba en **38,9 °C** y tenía **5 %** de copa de árboles. Providencia, a unos kilómetros,
  > **35,1 °C** y **13 %**. Casi **4 grados** de diferencia en la vereda donde la gente espera la micro o lleva
  > a sus hijos al colegio. Y si contamos árboles por habitante, Lo Espejo tiene **0,07** y Vitacura **2,5**:
  > casi 40 veces más. Plantar al azar no alcanza; cada metro de sombra tiene que ir donde más alivia."*
* Fuentes: `data/cifras_pitch.json` (Landsat 8/9 del 19-02-2026 y nuestro modelo de copa); árboles por
  habitante en `NOTAS PITCH.md` (Meta 2019 y Censo 2024, zona urbana bajo 900 m).

---

### 0:30 – 1:00 · Qué hace Viridis
* **Pantalla:** el mapa con las capas Calor, Árboles y Personas, y luego Aves y Abejas.
* **Orador:**
  > *"Viridis divide las 34 comunas del Gran Santiago en hexágonos del tamaño de una cuadra. En cada una cruza
  > la temperatura del suelo medida por Landsat, la copa de árboles de nuestro propio modelo sobre Sentinel-2
  > —que sigue al mapa de referencia de Meta con correlación **0,92**, contra **0,84** del mapa global de la
  > ESA— y las personas que viven ahí según el **Censo 2024**, más la cercanía a colegios, consultorios, metro y
  > paraderos. Con eso arma un índice de urgencia: 40 % calor, 40 % falta de árboles y 20 % personas.
  > Y suma a quienes también viven en la ciudad: **655.157** registros de aves y **1.603** de abejas nativas
  > desde 2015, de eBird, iNaturalist y museos, por barrio."*
* Fuente del viaje: `web/public/data/viaje.json` (`viaje_picaflor.py`: copa de nuestro modelo por cuadra y
  20.076 registros del picaflor chico en GBIF desde 2015). Fuente de la red completa: `web/public/data/red.json` (`red_conectada.py`, «todas», 100 km; personas en las
  cuadras de la red y sus vecinas). Fuente de la fauna: `data/fauna_h3.parquet` (GBIF, consultado el 22-11-2026; ver `CONTRATO.md`). Decirlo
  como «registros», no como censo: hay más observadores en parques y cerros.
* Un dato que sorprende, si hay tiempo: *"Donde hay más pasto el suelo está más caliente; donde hay más copa,
  más fresco. El verde que importa es el que da sombra."* (r = +0,46 y −0,50, `NOTAS PITCH.md`).

---

### 1:00 – 2:00 · Demo en vivo
1. **Elegir dónde.** Dejar elegidas Providencia y Cerro Navia (o encerrar unas cuadras con el lápiz: arrastrar
   pinta cuadras y volver al inicio del trazo rellena la zona). El resto de Santiago queda atenuado y la tabla
   muestra solo lo elegido, comparado con el promedio de Santiago.
2. **Trazar el corredor.** Ir a «Planificar»: con **3 km** de presupuesto, el corredor une parques existentes
   pasando por las cuadras más urgentes.
   > *"Entre las dos comunas, el corredor se va entero a Cerro Navia y cubre **13.295 personas**. Un trazado al
   > azar del mismo largo, **8.334**."*
3. **Para quién es el corredor.** Cambiar el perfil a «Aves» o «Abejas»: el corredor busca copa continua
   (aves) o piedras de paso con flores (abejas) entre las islas verdes. Bajo las cifras aparecen las especies
   de aves registradas en los barrios que cruza y los registros de abejas nativas (GBIF).
   > *"Este corredor no es solo sombra: cruza barrios donde se han registrado estas aves, y las conecta con el
   > cerro."* (Leer las especies y la cifra que muestre la pantalla.)
* **Ensayo:** decir siempre la cifra que muestre la pantalla. Las de este guion son con Providencia y Cerro
  Navia elegidas, 3 km y los pesos por defecto; con solo Cerro Navia el azar sube a 10.107, y con sensores de
  aire el corredor de todo Santiago puede cambiar. No dejar que el jurado elija una comuna a ciegas:
  con 3 km, en 11 comunas chicas o sin parques cercanos el corredor no sale.

---

### 2:00 – 2:40 · Números
* **Pantalla:** el bloque de cifras de «Planificar».
* **Orador:**
  > *"Con el mismo presupuesto de 3 km:*
  > *- entre Providencia y Cerro Navia, el corredor de Viridis cubre **13.295 personas**, contra **8.334** al
  > azar: **60 % más**;*
  > *- elegido sobre todo el Gran Santiago, cae en Pudahuel y cubre **10.023**, contra **7.002**: **43 % más**."*
* Fuente: `data/cifras_pitch.json` (`corredor` y `corredor_gran_santiago`), calculadas sin la temperatura del
  aire. No citar la urgencia media. No decir grados de enfriamiento: no tenemos un coeficiente publicado que
  citar.

---

### 2:40 – 3:00 · Cierre
* **Pantalla:** la sección «Santiago conectado», con «Las tres» elegido: apretar «Ver crecer la red» y dejar que
  la red llegue a 100 km mientras se habla.
* **Orador:**
  > *"Y si Santiago construye la red completa: con 100 km de corredores se unen **30 islas verdes** y **943.837
  > personas** quedan a una cuadra de la sombra. Viridis no necesita instalar nada: usa satélites públicos, el Censo, OpenStreetMap, las estaciones
  > meteorológicas oficiales y lo que miles de personas han observado de aves y abejas. Le dice a un municipio
  > por dónde plantar primero, para quién y por qué. Donde se necesita el verde. Gracias."*

---

## Preguntas difíciles

1. **"¿Por qué es Physical World y no solo un mapa?"**
   Todo sale de mediciones del mundo físico: el calor del suelo desde satélite, la temperatura máxima del aire
   de cada día en las estaciones oficiales de la Dirección Meteorológica y del SINCA (se actualiza sola cada
   noche), y aves y abejas observadas en la calle por personas (GBIF: eBird, iNaturalist). El corredor se
   traza para personas, aves o abejas según esos datos.
2. **"¿Qué tan bueno es su mapa de árboles?"**
   Correlación 0,92 con el mapa de Meta por cuadra, en comunas que el modelo no vio al entrenar (WorldCover de
   la ESA: 0,84). No ubica árboles individuales y se queda algo corto donde hay muchos árboles (Providencia:
   13,0 % contra 15,6 % de Meta). Fuente: `data/modelo_copa.json`.
3. **"¿Por qué la temperatura de febrero?"**
   El calor que importa para la sombra es el de verano, y el índice usa esa escena de verano completa sobre
   las 34 comunas.
4. **"¿Cuántos grados baja la temperatura con el corredor?"**
   No lo afirmamos: no hay un coeficiente publicado para Santiago que podamos citar. Lo que sí medimos es a
   cuánta gente y a qué cuadras llega cada metro de corredor.
5. **"¿Cómo se diferencia de Treepedia (MIT)?"**
   Treepedia mide verde visible en Street View. Viridis cruza copa de árboles con temperatura del suelo,
   población y fauna registrada, y traza un corredor bajo un presupuesto en km que une parques existentes,
   para personas, aves o abejas.
