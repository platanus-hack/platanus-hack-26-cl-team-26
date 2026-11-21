# VerdeH3 · Pitch de 3 Minutos y Guion de Demostración
**Platanus Hack 26 · Track Physical World**  
*Equipo VerdeH3 · Integrante 3 (Panel, Visualización & Pitch)*

---

## 🎯 Estructura y Cronograma del Pitch (180 Segundos)

```
[0:00 - 0:30] EL DOLOR URBANO: La brecha térmica invisible de Santiago
[0:30 - 1:00] LA SOLUCIÓN VERDEH3: Macro satélite + micro calle en grilla H3
[1:00 - 2:00] DEMOSTRACIÓN EN VIVO (Mesa del Jurado): El lazo físico cerrado
[2:00 - 2:40] IMPACTO Y NÚMEROS REALES: Maximizar enfriamiento por km
[2:40 - 3:00] CIERRE Y ESCALABILIDAD: Cero infraestructura nueva requerida
```

---

### Minuto 0:00 – 0:30 | La Brecha Térmica Invisible de Santiago
* **Qué se muestra en pantalla:**  
  Pestaña *"🎯 Pitch & Demo Jurado"* en `app.py`, mostrando las métricas de Cerro Navia vs. Providencia.
* **Qué dice el orador:**  
  > *"Santiago no solo es desigual en ingresos; es brutalmente desigual en sombra y temperatura.  
  > Mientras en Providencia y Las Condes la temperatura superficial de verano promedia **32.8 °C** con un **47%** de cobertura verde, a solo unos kilómetros al poniente, en Cerro Navia y Estación Central, la superficie hierve a **37.2 °C** con apenas un **6%** de áreas verdes.  
  > Son casi **5 grados Celsius de diferencia** en la vereda donde la gente camina, espera el transporte público o lleva a sus hijos al colegio. Plantar árboles al azar no alcanza: cada metro cuadrado de sombra debe colocarse donde más vidas alivia."*

---

### Minuto 0:30 – 1:00 | La Solución VerdeH3: Macro + Micro en Grilla H3
* **Qué se muestra en pantalla:**  
  El mapa 3D hexagonal extruido con los hexágonos de resolución 9 (~174 m por lado).
* **Qué dice el orador:**  
  > *"El satélite ve el calor cada 100 metros con Landsat y Sentinel-2, pero no puede ver qué pasa bajo la copa de un árbol o en una vereda estrecha. Por otro lado, las fotos a nivel de calle ven cada árbol, pero no la isla de calor completa.  
  > **VerdeH3 fusiona ambos mundos en una grilla hexagonal H3**: cruzamos temperatura satelital, índice de vegetación, equipamiento social (colegios y centros de salud) e imágenes de calle tomadas desde vehículos —que en producción se alimentan de las dashcams de los buses Red del transporte público— para priorizar qué corredor verde conviene plantar primero."*

---

### Minuto 1:00 – 2:00 | Demo Física en Vivo: El Lazo Cerrado (El Jurado Actúa)
* **Acción física:**  
  Se le pide a uno de los jueces que participe en la maqueta sobre la mesa.
* **Qué dice el orador:**  
  > *"Pero no vinimos a mostrar una simulación estática; esto es el track Physical World. Miren nuestra maqueta y nuestra cámara en vivo."*
* **Paso a paso de la interacción:**
  1. *"Invito a uno de los jurados a retirar o mover esta planta (árbol) de la vereda en la maqueta."*
  2. *(El juez mueve la planta)*.
  3. La cámara detecta en tiempo real la caída de sombra (de 65% a menos de 30% en menos de 1 segundo).
  4. El hexágono en el mapa 3D pasa inmediatamente a rojo por estrés térmico.
  5. El corredor verde se **recalcula automáticamente** en pantalla para absorber ese punto crítico.
  6. **Salida física instantánea:**  
     - La baliza parpadea en rojo.  
     - El parlante anuncia por voz TTS:  
       *«Alerta de estrés térmico detectada en vereda. Prioridad alta de arborización.»*
  7. *(Opcional)* Se muestra la curva real del día grabada por el teléfono en la ventana (`ventana_timelapse.csv`).

---

### Minuto 2:00 – 2:40 | Métricas de Impacto: Eficiencia Comprobada
* **Qué se muestra en pantalla:**  
  Métricas en tarjetas y gráfico comparativo de impacto (`assets/comparativa_impacto.png`).
* **Qué dice el orador:**  
  > *"Con un presupuesto municipal realista de apenas **3 kilómetros** de nuevo arbolado:  
  > - VerdeH3 beneficia a **más de 25.000 habitantes** directos que hoy viven bajo islas de calor severas.  
  > - Genera un **74% más de efectividad térmica y social** comparado con la planificación tradicional o trazados aleatorios.  
  > Cada dólar y cada árbol invertido tiene el triple de impacto."*

---

### Minuto 2:40 – 3:00 | Cierre y Escalabilidad
* **Qué se muestra en pantalla:**  
  El mapa completo de Santiago con el corredor interconectando parques y colegios.
* **Qué dice el orador:**  
  > *"Lo más potente de VerdeH3: **no requiere instalar costosas redes de sensores en cada esquina de la ciudad**.  
  > Aprovecha lo que las ciudades ya pagan —satélites públicos y cámaras móviles en flotas de buses municipales— y lo transforma en una respuesta física directa, auditada en vivo para enfriar donde más duele.  
  > Muchas gracias."*

---

## 🛡️ Guía Rápida para Preguntas Difíciles del Jurado (Q&A)

1. **"¿Por qué esto no es solo una app de mapas o una simulación?"**
   - *Respuesta:* Porque el núcleo interactúa bidireccionalmente con el entorno físico en tiempo real. La cámara física audita la sombra real de la vereda segundo a segundo (entrada física) y dispara una baliza y advertencia acústica (salida física). El lazo se cierra en el mundo real, no en una base de datos estática.

2. **"¿Qué pasa si se nubla o es de noche?"**
   - *Respuesta:* Es un fenómeno meteorológico real que el sistema registra fielmente en el time-lapse. Para garantizar una demo 100% confiable y sin depender del clima, la maqueta cuenta con su propia fuente lumínica calibrada.

3. **"¿Cómo se diferencia de Treepedia del MIT Senseable City Lab?"**
   - *Respuesta:* Treepedia mide el verde visible desde Street View de forma pasiva y estática. VerdeH3 combina esa visión a nivel de calle con la temperatura satelital térmica (LST) en una grilla H3, calcula rutas de plantación con optimización matemática bajo presupuesto, y audita la sombra en vivo con hardware físico.

4. **"¿De dónde salen las fotos en una implementación real?"**
   - *Respuesta:* Los buses del sistema Red de Santiago recorren todas las comunas a diario y ya cuentan con cámaras frontales. En lugar de procesar petabytes sin rumbo, VerdeH3 audita los tramos más calientes automáticamente.
