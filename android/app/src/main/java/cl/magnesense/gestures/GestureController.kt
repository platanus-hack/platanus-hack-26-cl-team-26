package cl.magnesense.gestures

import android.os.SystemClock
import cl.magnesense.actions.Device
import cl.magnesense.data.ActivationMode
import cl.magnesense.data.AppSettings
import cl.magnesense.engine.AccessController
import cl.magnesense.feedback.SoundPlayer
import cl.magnesense.feedback.Speaker
import cl.magnesense.remote.ServerEvent
import cl.magnesense.remote.ServerState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/** Modo en uso en este momento (puede diferir del elegido si no hay detector de gestos). */
data class GestureStatus(
    val chosen: ActivationMode = ActivationMode.SCANNING,
    /** Los gestos aprendidos estan mandando (modo elegido y servidor en vivo). */
    val gesturesActive: Boolean = false,
    /** Se eligio gestos pero no hay servidor: se volvio al escaneo. */
    val fallback: Boolean = false,
)

/** Un gesto aprendido que se disparo, con lo que hizo (para resaltar en pantalla). */
data class GestureFired(val detector: String, val target: String?, val deviceId: String?, val atMs: Long)

/**
 * Ejecuta los gestos aprendidos: escucha los eventos del detector de gestos ([LocalGestures],
 * en el celular), aplica la regla de cada uno y hace la accion enlazada (un dispositivo,
 * abrir el escaneo, la cancion o el cuack).
 * En modo gestos, la activacion del detector local se ignora para no actuar dos veces;
 * si la fuente de gestos se cae mas de [FALLBACK_AFTER_MS], vuelve al escaneo y lo dice en voz alta.
 */
class GestureController(
    private val scope: CoroutineScope,
    private val source: StateFlow<ServerState>,
    events: SharedFlow<ServerEvent>,
    private val access: AccessController,
    private val settings: StateFlow<AppSettings>,
    private val speaker: Speaker,
    private val sounds: SoundPlayer,
    private val log: (String) -> Unit,
) {
    private val _status = MutableStateFlow(GestureStatus())
    val status: StateFlow<GestureStatus> = _status.asStateFlow()

    /** Todos los disparos, tambien en modo escaneo (sirve para probar gestos). */
    private val _fired = MutableSharedFlow<GestureFired>(extraBufferCapacity = 16)
    val fired: SharedFlow<GestureFired> = _fired.asSharedFlow()

    /** Mientras se ensena un gesto, el iman local no debe armar el escaneo. */
    @Volatile
    var teaching = false
        set(value) {
            field = value
            updateSuppress()
        }

    private val lastFire = HashMap<String, Long>()
    private var disconnectedSince = 0L

    init {
        scope.launch { events.collect(::onServerEvent) }
        scope.launch {
            while (isActive) {
                updateStatus()
                delay(CHECK_MS)
            }
        }
    }

    private fun updateStatus() {
        val chosen = settings.value.activationMode
        val now = SystemClock.elapsedRealtime()
        val connected = source.value.connected
        if (connected) disconnectedSince = 0L else if (disconnectedSince == 0L) disconnectedSince = now
        val previous = _status.value
        val next = when {
            chosen != ActivationMode.GESTURES -> GestureStatus(chosen)
            connected -> GestureStatus(chosen, gesturesActive = true)
            // Margen corto antes de rendirse: una reconexion rapida no debe cambiar de modo.
            now - disconnectedSince < FALLBACK_AFTER_MS && previous.gesturesActive -> previous
            else -> GestureStatus(chosen, fallback = true)
        }
        if (next == previous) return
        _status.value = next
        updateSuppress()
        if (previous.chosen == chosen && chosen == ActivationMode.GESTURES) {
            if (next.fallback && previous.gesturesActive) speaker.speak("Sin gestos, vuelvo al escaneo", queue = true)
            if (next.gesturesActive && previous.fallback) speaker.speak("Gestos aprendidos activos", queue = true)
        }
    }

    /** El iman local arma el escaneo solo en modo escaneo, y nunca mientras se ensena un gesto. */
    private fun updateSuppress() {
        access.suppressMagnetActivation =
            teaching || _status.value.gesturesActive || settings.value.activationMode == ActivationMode.PULSES
    }

    private fun onServerEvent(e: ServerEvent) {
        val detector = source.value.phase2.detectors.firstOrNull { it.name == e.detector } ?: return
        if (!GestureMatcher.fires(detector, e)) return
        val now = SystemClock.elapsedRealtime()
        if (now - (lastFire[e.detector] ?: 0L) < DEBOUNCE_MS) return
        lastFire[e.detector] = now

        val target = settings.value.gestureBindings[e.detector]
        val device: Device? = access.devices.value.firstOrNull { it.id == target }
        _fired.tryEmit(GestureFired(e.detector, target, device?.id, now))
        if (!_status.value.gesturesActive) return

        when {
            target == AppSettings.BIND_SONG -> {
                val playing = sounds.toggleSong()
                log("Gesto '${e.detector}' → ${if (playing) "canción" else "canción parada"}")
            }
            target == AppSettings.BIND_QUACK -> {
                log("Gesto '${e.detector}' → cuack")
                sounds.quack()
            }
            target == AppSettings.BIND_SCAN -> {
                log("Gesto '${e.detector}' → escaneo")
                access.scanning.onActivation(now)
            }
            device != null -> {
                log("Gesto '${e.detector}' → ${device.name}")
                access.runByTouch(device)
            }
        }
    }

    private companion object {
        const val CHECK_MS = 500L
        const val FALLBACK_AFTER_MS = 5_000L
        /** Un mismo gesto no se ejecuta dos veces en menos de esto. */
        const val DEBOUNCE_MS = 800L
    }
}
