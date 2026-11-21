# MagneSense para Android

App que detecta un imán pequeño en un dedo con el magnetómetro del celular y, por
escaneo de un solo interruptor, controla enchufes inteligentes y avisa al cuidador.
Solo software: celular sin modificar + imán comprado + enchufes comerciales (Shelly u otros con URL HTTP).

## Requisitos

- Android Studio (trae el SDK y un JDK). Probado con Android Studio 2026.2, JDK 25 (JBR), SDK 37.
- Celular Android 8.0+ (minSdk 26) con magnetómetro. El giroscopio es opcional, pero recomendado.

## Compilar

En Windows (PowerShell), desde `android/`:

```powershell
$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
.\gradlew.bat assembleDebug
```

En macOS/Linux:

```bash
export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"   # o tu JDK 17+
./gradlew assembleDebug
```

El APK queda en `app/build/outputs/apk/debug/app-debug.apk`.
Si Gradle no encuentra el SDK, crea `local.properties` con `sdk.dir=C:/Users/<usuario>/AppData/Local/Android/Sdk`
(barras normales).

Pruebas unitarias (detector, escaneo, formato de telemetría):

```bash
./gradlew testDebugUnitTest
```

## Instalar

1. En el celular: Ajustes → Acerca del teléfono → tocar 7 veces "Número de compilación" → Opciones de desarrollador → **Depuración USB**.
2. Conectar por USB y aceptar "¿Permitir depuración USB?".
3. `adb install -r app/build/outputs/apk/debug/app-debug.apk`

O copiar el APK al celular y abrirlo (permitir "instalar apps desconocidas").

## Uso (2 minutos)

1. Abrir MagneSense y aceptar notificaciones. Aparece la notificación fija "MagneSense está escuchando":
   la detección sigue con la pantalla apagada.
2. **Calibrar**: dejar el celular quieto 10 s, luego acercar el imán 5 veces con el mismo movimiento.
   El resultado dice si la señal es fuerte y si el movimiento fue consistente.
3. **Control**: acercar el imán una vez para empezar el escaneo; se resalta y se dice en voz alta
   una opción cada 2 s. Acercar el imán de nuevo elige la opción resaltada.
   "Llamar cuidador" pide confirmación ("Sí, llamar" / "No, cancelar"), que se cancela sola a los 10 s.
4. Si el celular se mueve, la app entra **En pausa** y vuelve a medir la base cuando queda quieto.
5. **Ajustes** (para el cuidador): URL de encendido y apagado de cada enchufe
   (Shelly: `http://IP/relay/0?turn=on` / `?turn=off`, con botones para probar), teléfono y webhook del cuidador,
   velocidad del escaneo, sensibilidad, tiempo de sostener, servidor e inicio automático.
   Sin URL, un dispositivo funciona en modo demostración (solo cambia en pantalla).
6. Si el imán llega desde otro ángulo, Control muestra "Detecté el imán, pero en otra dirección". En **Debug → Ajuste fino**
   se puede ampliar el cono de dirección, aceptar el imán dado vuelta o desactivar el chequeo, y bajar la fuerza mínima.
7. **Historial** muestra los últimos eventos. **Debug** muestra |ΔB|, coseno, umbrales, giroscopio y frecuencia de muestreo.

## Panel web (server.py)

La app puede enviar el magnetómetro al `server.py` del repositorio con el mismo formato que la app
Sensor Logger, así el panel en vivo funciona igual:

1. En el notebook: `pip install -r requirements.txt` y `python server.py` (muestra la IP).
2. En la app: Ajustes → Servidor → `http://IP-del-notebook:8000` (misma red Wi-Fi).
   Por cable USB también sirve: `adb reverse tcp:8000 tcp:8000` y usar `http://127.0.0.1:8000`.
3. El panel muestra la señal, y los eventos de la app (activación, opción elegida, pausa) aparecen
   en la línea de mensajes vía `POST /app-event`.

No definas `ACTUATOR_ON_URL`/`ACTUATOR_OFF_URL` en el servidor si la app ya controla esos mismos enchufes:
el detector del servidor también los alternaría.

## Repetir sesiones grabadas

`server.py` guarda sesiones en `data/session_*.csv`. Para pasarlas por el detector de Kotlin
y ver activaciones por minuto:

```bash
./gradlew :app:testDebugUnitTest --tests '*CsvReplayTest*' -i
```

## Arquitectura

```
cl.magnesense
├── sensor/     SensorService (primer plano, tipo health, wake lock), SensorReader (200 Hz), BootReceiver
├── detector/   Detector en Kotlin puro + DetectorConfig (todos los parámetros) + modelos
├── engine/     Engine (sensores → detector), AccessController (detector → escaneo → acciones)
├── scanning/   ScanningController en Kotlin puro (escaneo de un interruptor y confirmación)
├── actions/    Device, DeviceActions (HTTP 2 s, cuidador: webhook + llamada), Http
├── feedback/   Speaker (TextToSpeech es-CL), Haptics (sonido y vibración)
├── telemetry/  TelemetryClient y SensorLoggerFormat (POST /data y /app-event)
├── data/       SettingsStore (ajustes y calibración), EventLog (historial)
└── ui/         Compose: control, calibration, settings, history, debug, theme, components
```

**Detector** (`detector/Detector.kt`): suaviza B, compara |B − base| con umbrales
`on = max(6σ, 0,5 × pico mediano, 1 µT)` y `off = on / 2`. Exige 300 ms sobre `on`
con la dirección correcta (cos ≥ 0,6 respecto a la calibrada, o más permisivo si los acercamientos de la calibración variaron más; si no, evento IGNORED y aviso en pantalla) y tiene
1 s de refractario con bajada bajo `off`. El giroscopio (|ω| > 0,3 rad/s) pausa y, tras 1 s quieto,
vuelve a medir la base durante 0,5 s. Además sigue la deriva lenta solo en reposo y avisa si el sensor se satura.

Notas:
- `HIGH_SAMPLING_RATE_SENSORS` es un permiso de instalación (no se pide al usuario). Es requisito del servicio
  en primer plano tipo `health` en Android 14+.
- `usesCleartextTraffic` está activado porque los enchufes y `server.py` usan `http://` en la red local.
- La llamada directa al cuidador necesita el permiso de llamadas (botón en Ajustes); sin él se abre el marcador.
  Android solo permite abrir la llamada si la app está en pantalla; para eso Control mantiene la pantalla encendida.
