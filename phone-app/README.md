# MagneSense Logger (app del teléfono)

App propia, al estilo de Sensor Logger. Lee el **magnetómetro** y el **giroscopio** del teléfono y los envía a `server.py` (`POST /data`). Usa el mismo JSON que el HTTP Push de Sensor Logger, así que el servidor la recibe sin cambios.

| Sensor | Nombre enviado | Unidad |
|---|---|---|
| Magnetómetro sin calibrar (por defecto) | `magnetometeruncalibrated` | µT |
| Magnetómetro calibrado | `magnetometer` | µT |
| Giroscopio | `gyroscope` | rad/s |

Los timestamps se envían en nanosegundos desde 1970, igual que Sensor Logger. Las lecturas se agrupan en paquetes cada 40 ms (25 por segundo), así el servidor las recibe con poco retraso. Si el servidor no responde, se reintentan, guardando hasta 6000 lecturas.

## Probarla (Android o iPhone, sin compilar)

1. Instala **Expo Go** en el teléfono desde Play Store o App Store.
2. En el notebook:
   ```
   python server.py          # en la raíz del repo; imprime la IP para el teléfono
   cd phone-app
   npm install
   npx expo start
   ```
3. Escanea el QR. En Android, con Expo Go. En iPhone, con la cámara.
4. En la app, escribe la IP que imprimió `server.py` (por ejemplo `192.168.1.20:8000`). Toca **Probar conexión** y luego **Transmitir**.

El teléfono y el notebook deben estar en la misma red WiFi. Si la red bloquea conexiones entre equipos (pasa en redes de eventos), usa el hotspot del teléfono o `npx expo start --tunnel`. El túnel solo sirve para cargar la app: los datos siguen yendo directo a la IP del notebook.

## Pestaña Agente

Requiere el servidor de la rama `feat/agente` (`server.py` con el agente y `ANTHROPIC_API_KEY` definida).

- **Chat:** se habla con el agente desde el celular, por ejemplo: *"si muevo el imán de izquierda a derecha se apaga la luz, y de derecha a izquierda se prende"*.
- **Calibración guiada:** cuando el agente pide grabar un movimiento, aparece un aviso a pantalla completa. Primero "Prepárate", en azul, y luego "AHORA", en amarillo, con el movimiento ("Mueve el imán IZQUIERDA ➜ DERECHA"), el número de intento y la cuenta regresiva. No hay que tocar el celular: tocarlo mueve el magnetómetro.
- **Reglas:** se ven las reglas creadas. Las acciones `http` o `comando` pendientes se pueden aprobar aquí o en el panel.
- **Transmisión:** sigue activa al cambiar de pestaña. Hay que empezar a transmitir en Sensores.

La app usa el mismo WebSocket que el panel web (`/ws`) y `POST /agent`.

## Opciones

- **Frecuencia**: 50, 100 o 200 Hz. Usa 200 Hz por defecto. Android 12+ no entrega más de 200 Hz por sensor, y en iPhone el magnetómetro suele llegar a ~100 Hz. La pantalla muestra la frecuencia real obtenida.
- **Pantalla**: se refresca ~30 veces por segundo. Cada barra del gráfico va del mínimo al máximo de ese instante, así se ven también los movimientos más cortos.
- **Retraso en el servidor**: además del envío, el detector de la fase 1 espera que la señal pase el umbral durante "duración mínima" (150 ms por defecto). Puedes bajarla en el panel si necesitas que reaccione antes, con más riesgo de falsas alarmas.
- **Sin calibrar**: el servidor prefiere esta señal, porque el magnetómetro calibrado puede saltar cuando el sistema se recalibra solo.
- La pantalla se mantiene encendida mientras se transmite. Si la app pasa a segundo plano, el envío se detiene.

## APK instalable (opcional)

Sin Android Studio: `npx eas-cli@latest build -p android --profile preview`. Requiere una cuenta Expo y un `eas.json`. Para un APK que envíe por HTTP (no HTTPS) hay que permitir tráfico sin cifrar con `expo-build-properties` (`android.usesCleartextTraffic: true`). Expo Go ya lo permite.
