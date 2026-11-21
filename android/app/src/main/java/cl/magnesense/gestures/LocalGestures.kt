package cl.magnesense.gestures

import android.content.Context
import cl.magnesense.data.HistoryKind
import cl.magnesense.detector.Vec3
import cl.magnesense.gestures.local.GestureBank
import cl.magnesense.gestures.local.GestureSpec
import cl.magnesense.remote.DetectorType
import cl.magnesense.remote.RemoteDetector
import cl.magnesense.remote.ServerEvent
import cl.magnesense.remote.ServerPhase2
import cl.magnesense.remote.ServerState
import cl.magnesense.remote.TrainRequest
import cl.magnesense.remote.TrainResult
import cl.magnesense.sensor.SensorSink
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.Locale

/** Lo que muestra en vivo el asistente de inicio. */
data class GestureLive(
    val calibrating: Boolean = true,
    /** |B − reposo| suavizado (µT). */
    val signal: Double = 0.0,
    /** Ruido en reposo σ (µT). */
    val noise: Double = 0.0,
    val phoneMoving: Boolean = false,
    /** Umbral mas bajo de los gestos aprendidos, o el piso si no hay. */
    val threshold: Double = 1.0,
)

/**
 * Gestos aprendidos en el celular, sin servidor. Recibe el magnetometro y el giroscopio,
 * corre el [GestureBank] y publica el mismo estado y eventos que antes daba server.py,
 * asi la pantalla de Gestos y el [GestureController] no cambian de forma.
 * Los ejemplos y gestos se guardan en disco y sobreviven al reinicio.
 */
class LocalGestures(
    context: Context,
    /** Registro tecnico (todo, con numeros). */
    private val diag: (String) -> Unit = {},
    /** Historial para el cuidador (solo lo importante). */
    private val history: (HistoryKind, String) -> Unit = { _, _ -> },
) : SensorSink {

    private val file = File(context.filesDir, FILE_NAME)
    private val bank = GestureBank()
    private val lock = Any()

    private val _state = MutableStateFlow(ServerState(connected = true))
    val state: StateFlow<ServerState> = _state.asStateFlow()

    private val _events = MutableSharedFlow<ServerEvent>(extraBufferCapacity = 64, onBufferOverflow = BufferOverflow.DROP_OLDEST)
    val events: SharedFlow<ServerEvent> = _events.asSharedFlow()

    private val _live = MutableStateFlow(GestureLive())
    val live: StateFlow<GestureLive> = _live.asStateFlow()

    private var lastPublish = 0.0
    private var wasCalibrating = true
    private var wasMoving = false

    init {
        synchronized(lock) { load() }
        publish()
    }

    override fun onMagnetometer(tNanos: Long, value: Vec3) {
        val t = tNanos / NANOS
        val out = synchronized(lock) { bank.step(t, value) }
        for ((e, muted) in out) {
            report(e, muted)
            // Grabando o recien calibrado: no disparar nada.
            if (!muted) _events.tryEmit(ServerEvent(e.detector, e.kind, t, duration = e.duration))
        }
        watchTransitions(t)
        if (out.any { it.first.kind in COUNTED } || t - lastPublish >= PUBLISH_S) {
            lastPublish = t
            publish()
        }
    }

    override fun onGyroscope(tNanos: Long, value: Vec3) {
        synchronized(lock) { bank.gyro(tNanos / NANOS, value) }
    }

    private fun report(e: cl.magnesense.gestures.local.GestureEvent, muted: Boolean) {
        val quiet = if (muted) " [silenciado: calibrando o grabando]" else ""
        val text = when (e.kind) {
            "start" -> "Gesto '%s' empezó: señal %.2f µT, umbral %.2f µT, coseno %.2f".format(
                Locale.US, e.detector, e.signal ?: 0.0, e.limit ?: 0.0, e.cosine ?: 1.0,
            )
            "too_strong" -> "Gesto '%s' descartado por golpe: %.1f µT > tope %.1f µT".format(Locale.US, e.detector, e.signal ?: 0.0, e.limit ?: 0.0)
            "drift" -> "Gesto '${e.detector}': cambio lento (deriva), se toma como reposo nuevo"
            "stuck" -> "Gesto '${e.detector}': el campo quedó alto más de 6 s (¿imán quieto cerca?)"
            "end" -> "Gesto '%s' terminó (%.2f s)".format(Locale.US, e.detector, e.duration ?: 0.0)
            else -> "Gesto '${e.detector}': ${e.kind}"
        }
        diag(text + quiet)
        when (e.kind) {
            "too_strong" -> history(HistoryKind.IGNORED, "Descartado: golpe más fuerte que lo aprendido ('${e.detector}')")
            "drift" -> history(HistoryKind.IGNORED, "Descartado: cambio lento ('${e.detector}')")
        }
    }

    private fun watchTransitions(t: Double) {
        val (calibrating, moving, noise) = synchronized(lock) {
            Triple(bank.pipeline.calibrating, bank.pipeline.phoneMoving(t), bank.pipeline.noise)
        }
        if (wasCalibrating && !calibrating) {
            diag("Calibrado: ruido en reposo σ = %.3f µT".format(Locale.US, noise))
            history(HistoryKind.CALIBRATION, "Gestos: calibrado (ruido %.2f µT)".format(Locale.US, noise))
        }
        if (moving != wasMoving) diag(if (moving) "Celular moviéndose (giroscopio): detección en pausa" else "Celular quieto: nuevo reposo")
        wasCalibrating = calibrating
        wasMoving = moving
    }

    /** Mide de nuevo el reposo: 0,5 s descartados (el toque) y 2 s quieto. */
    fun recalibrate() {
        synchronized(lock) { bank.recalibrate() }
        diag("Recalibrar pedido")
        publish()
    }

    fun startRecording(label: String): String? = synchronized(lock) { bank.startRecording(label) }.also {
        diag(if (it == null) "Grabando ejemplo de '$label'" else "No se pudo grabar '$label': $it")
        publish()
    }

    fun stopRecording(): Int {
        val (label, n, peak) = synchronized(lock) {
            val label = bank.recording
            val n = bank.stopRecording().also { save() }
            val peak = bank.examples[label]?.lastOrNull()?.maxByOrNull { it.norm }
            Triple(label, n, peak)
        }
        diag(
            if (peak == null) "Ejemplo de '$label' vacío (sin muestras)"
            else "Ejemplo %d de '%s': pico %.2f µT, dirección (%.2f, %.2f, %.2f)".format(
                Locale.US, n, label, peak.norm, peak.x / peak.norm, peak.y / peak.norm, peak.z / peak.norm,
            ),
        )
        publish()
        return n
    }

    fun clearExamples(label: String) {
        synchronized(lock) {
            bank.clearExamples(label)
            save()
        }
        publish()
    }

    fun train(request: TrainRequest): TrainResult {
        if (request.type != DetectorType.EVENT) return TrainResult(ok = false, error = "En el celular solo hay gestos breves")
        val spec = GestureSpec(
            name = request.name,
            label = request.label ?: request.name,
            trigger = request.trigger ?: GestureMatcher.TRIGGER_ANY,
            minOnMs = request.minOnMs ?: DEFAULT_MIN_ON_MS,
        )
        val r = synchronized(lock) { bank.train(spec).also { if (it.ok) save() } }
        diag(
            if (r.ok) "Gesto '%s' creado: pico %.2f µT, umbral %.2f µT, consistencia %.2f, regla %s, mínimo %d ms%s".format(
                Locale.US, r.name, r.peak ?: 0.0, r.threshold ?: 0.0, r.consistency ?: 0.0, spec.trigger, spec.minOnMs,
                r.warning?.let { " · $it" } ?: "",
            ) else "No se pudo crear '${spec.name}': ${r.error}",
        )
        publish()
        return TrainResult(ok = r.ok, detector = r.name, error = r.error, consistency = r.consistency, warning = r.warning)
    }

    fun removeDetector(name: String) {
        diag("Gesto '$name' eliminado")
        synchronized(lock) {
            bank.remove(name)
            save()
        }
        publish()
    }

    /** Lo que dura como minimo un gesto ya creado, o null si no existe. */
    fun minOnMs(name: String): Int? = synchronized(lock) { bank.savedSpecs.firstOrNull { it.name == name }?.minOnMs }

    private fun publish() {
        val (s, l) = synchronized(lock) {
            val p = bank.pipeline
            val t = p.lastT ?: 0.0
            val detectors = bank.detectors.map { b ->
                RemoteDetector(b.detector.name, DetectorType.EVENT, b.trigger, b.detector.active, b.detector.count)
            }
            val thr = bank.detectors.minOfOrNull { it.detector.threshold(p.noise) } ?: maxOf(6 * p.noise, 1.0)
            ServerState(
                connected = true,
                phase2 = ServerPhase2(p.calibrating, p.noise, p.gyroSeen, p.phoneMoving(t), detectors),
                recording = bank.recording,
                examples = bank.examples.mapValues { it.value.size },
            ) to GestureLive(p.calibrating, bank.lastSignal, p.noise, p.phoneMoving(t), thr)
        }
        _state.value = s
        _live.value = l
    }

    // --- Disco ---------------------------------------------------------------

    private fun save() {
        val o = JSONObject()
        val ex = JSONObject()
        for ((label, list) in bank.examples) {
            ex.put(label, JSONArray(list.map { sample -> JSONArray(sample.flatMap { listOf(r(it.x), r(it.y), r(it.z)) }) }))
        }
        o.put("examples", ex)
        o.put(
            "gestures",
            JSONArray(
                bank.savedSpecs.map {
                    JSONObject().put("name", it.name).put("label", it.label).put("trigger", it.trigger).put("minOnMs", it.minOnMs)
                },
            ),
        )
        runCatching {
            val tmp = File(file.parentFile, "$FILE_NAME.tmp")
            tmp.writeText(o.toString())
            tmp.renameTo(file)
        }
    }

    private fun load() {
        val o = runCatching { JSONObject(file.readText()) }.getOrNull() ?: return
        runCatching {
            val ex = o.getJSONObject("examples")
            for (label in ex.keys()) {
                val arr = ex.getJSONArray(label)
                bank.examples[label] = (0 until arr.length()).map { i ->
                    val flat = arr.getJSONArray(i)
                    (0 until flat.length() / 3).map { j -> Vec3(flat.getDouble(3 * j), flat.getDouble(3 * j + 1), flat.getDouble(3 * j + 2)) }
                }.toMutableList()
            }
            val gs = o.getJSONArray("gestures")
            for (i in 0 until gs.length()) {
                val g = gs.getJSONObject(i)
                bank.train(
                    GestureSpec(
                        g.getString("name"),
                        g.optString("label", g.getString("name")),
                        g.optString("trigger", GestureMatcher.TRIGGER_ANY),
                        g.optInt("minOnMs", DEFAULT_MIN_ON_MS),
                    ),
                )
            }
        }
    }

    private fun r(v: Double) = Math.round(v * 1000) / 1000.0

    companion object {
        const val DEFAULT_MIN_ON_MS = 160
        /** "Filtrar fasciculaciones": solo cuentan los gestos de 300 ms o mas. */
        const val FILTER_TWITCH_MIN_ON_MS = 300
        private const val FILE_NAME = "gestures.json"
        private const val NANOS = 1e9
        private const val PUBLISH_S = 0.1
        private val COUNTED = setOf("start", "short", "long", "double")
    }
}
