# Viridis · Pitch de 3 minutos y guion de demo
**Platanus Hack 26 · Track Physical World**

Todas las cifras de este guion salen de archivos del repo; al lado de cada una va su fuente. Las mismas cifras,
con más detalle y lo que no hay que decir, están en `NOTAS PITCH.md`.

---

## Estructura (180 segundos)

```
[0:00 - 0:30] El problema: la brecha de calor y de sombra dentro de Santiago
[0:30 - 1:00] Viridis: calor, copa y personas, cuadra por cuadra, en las 34 comunas
[1:00 - 2:00] Demo en vivo: elegir dónde, trazar el corredor y corregirlo con una foto de la calle
[2:00 - 2:40] Números: cuánta gente cubre el corredor frente a un trazado al azar
[2:40 - 3:00] Cierre: datos públicos, sin sensores nuevos en cada esquina
```

---

### 0:00 – 0:30 · Donde se necesita el verde
* **Pantalla:** la portada de la página («Donde se necesita el verde») y luego «Datos clave» con Providencia
  y Cerro Navia elegidas, para que la tabla muestre las dos comunas lado a lado.
* **Orador:**
  > *"Santiago no es desigual solo en ingresos: también en sombra. La tarde del 19 de febrero de 2026, el suelo
  > de Cerro Navia estaba en **38,9 °C** y tenía **5 %** de copa de árboles. Providencia, a unos kilómetros,
  > **35,1 °C** y **13 %**. Casi **4 grados** de diferencia en la vereda donde la gente espera la micro o lleva
  > a sus hijos al colegio. Y si contamos árboles por habitante, Lo Espejo tiene **0,07** y Vitacura **2,5**:
  > casi 40 veces más. Plantar al azar no alcanza; cada metro de sombra tiene que ir donde más alivia."*
* Fuentes: `data/cifras_pitch.json` (Landsat 8/9 del 19-02-2026 y nuestro modelo de copa); árboles por
  habitante en `NOTAS PITCH.md` (Meta 2019 y Censo 2024, zona urbana bajo 900 m).

---

### 0:30 – 1:00 · Qué hace Viridis
* **Pantalla:** el mapa con las capas Calor, Copa de árboles y Personas.
* **Orador:**
  > *"Viridis divide las 34 comunas del Gran Santiago en hexágonos del tamaño de una cuadra. En cada una cruza
  > la temperatura del suelo medida por Landsat, la copa de árboles de nuestro propio modelo sobre Sentinel-2
  > —que sigue al mapa de referencia de Meta con correlación **0,92**, contra **0,84** del mapa global de la
  > ESA— y las personas que viven ahí según el **Censo 2024**, más la cercanía a colegios, consultorios, metro y
  > paraderos. Con eso arma un índice de urgencia: 40 % calor, 40 % falta de árboles y 20 % personas."*
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
3. **El mundo físico entra al mapa.** Con el teléfono, sacar una foto de una calle (o mostrar una ya subida).
   Claude revisa que la foto sirva y estima cuánta copa se ve; esa cuadra queda marcada como verificada en
   terreno y el índice usa la foto junto al satélite. Si hay sensores de aire en vivo (SINCA, Sensor.Community)
   en suficientes barrios, también entran al índice de calor.
* **Ensayo:** decir siempre la cifra que muestre la pantalla. Las de este guion son con Providencia y Cerro
  Navia elegidas, 3 km y los pesos por defecto; con solo Cerro Navia el azar sube a 10.107, y con sensores de
  aire activos el corredor de todo Santiago puede cambiar. No dejar que el jurado elija una comuna a ciegas:
  con 3 km, en 11 comunas chicas o sin parques cercanos el corredor no sale.

---

### 2:00 – 2:40 · Números
* **Pantalla:** el bloque de cifras de «Planificar».
* **Orador:**
  > *"Con el mismo presupuesto de 3 km:*
  > *- entre Providencia y Cerro Navia, el corredor de Viridis cubre **13.295 personas**, contra **8.334** al
  > azar: **60 % más**;*
  > *- elegido sobre todo el Gran Santiago, cae en Pudahuel y cubre **10.023**, contra **7.002**: **43 % más**."*
* Fuente: `data/cifras_pitch.json` (`corredor` y `corredor_gran_santiago`), calculadas sin aire en vivo ni
  fotos de terreno. No citar la urgencia media: cambió de escala al sumar el peso de biodiversidad. No decir
  grados de enfriamiento: no tenemos un coeficiente publicado que citar.

---

### 2:40 – 3:00 · Cierre
* **Pantalla:** el mapa completo con las islas verdes (San Cristóbal, Renca, Santa Lucía, Parque O'Higgins).
* **Orador:**
  > *"Viridis no necesita instalar sensores en cada esquina: usa satélites públicos, el Censo, OpenStreetMap
  > y una foto desde el teléfono cuando hace falta confirmar una cuadra. Le dice a un municipio por dónde
  > plantar primero, y por qué. Donde se necesita el verde. Gracias."*

---

## Preguntas difíciles

1. **"¿Por qué es Physical World y no solo un mapa?"**
   La calle corrige al satélite: una foto con GPS desde el teléfono, validada por Claude, cambia la copa
   estimada de esa cuadra y puede mover el corredor. Además el índice de calor puede tomar la temperatura del
   aire de sensores en vivo (SINCA y Sensor.Community).
2. **"¿Qué tan bueno es su mapa de árboles?"**
   Correlación 0,92 con el mapa de Meta por cuadra, en comunas que el modelo no vio al entrenar (WorldCover de
   la ESA: 0,84). No ubica árboles individuales y se queda algo corto donde hay muchos árboles (Providencia:
   13,0 % contra 15,6 % de Meta). Fuente: `data/modelo_copa.json`.
3. **"¿Por qué la temperatura de febrero?"**
   El calor que importa para la sombra es el de verano, y el índice usa esa escena de verano completa sobre
   las 34 comunas. Las escenas más nuevas están en la sección «Histórico» de la página.
4. **"¿Cuántos grados baja la temperatura con el corredor?"**
   No lo afirmamos: no hay un coeficiente publicado para Santiago que podamos citar. Lo que sí medimos es a
   cuánta gente y a qué cuadras llega cada metro de corredor.
5. **"¿Cómo se diferencia de Treepedia (MIT)?"**
   Treepedia mide verde visible en Street View. Viridis cruza copa de árboles con temperatura del suelo y
   población, y traza un corredor bajo un presupuesto en km que une parques existentes.
