package cl.magnesense.telemetry

import android.os.SystemClock
import cl.magnesense.actions.Http
import cl.magnesense.detector.Vec3
import cl.magnesense.sensor.SensorHub
import cl.magnesense.sensor.SensorSink
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.util.UUID

data class TelemetryStatus(
    val enabled: Boolean = false,
    val connected: Boolean = false,
    val samplesSent: Long = 0,
    val lastError: String? = null,
)

/**
 * Envia el magnetometro a server.py (POST /data, formato Sensor Logger) cada ~100 ms y
 * los eventos de la app a POST /app-event, para que el panel web siga funcionando.
 * Si el servidor no responde, descarta lo viejo y reintenta mas tarde: nunca frena la deteccion.
 */
class TelemetryClient(scope: CoroutineScope) : SensorSink {

    @Volatile
    var baseUrl: String = ""
        set(value) {
            field = value.trim().trimEnd('/')
            _status.value = _status.value.copy(enabled = field.isNotEmpty(), connected = false, lastError = null)
        }

    private val _status = MutableStateFlow(TelemetryStatus())
    val status: StateFlow<TelemetryStatus> = _status.asStateFlow()

    private val samples = ArrayDeque<SensorSample>()
    private val events = ArrayDeque<String>()
    private val sessionId = UUID.randomUUID().toString()
    private var messageId = 0L
    private var backoffUntil = 0L

    init {
        scope.launch {
            while (isActive) {
                delay(PERIOD_MS)
                flush()
            }
        }
    }

    override fun onMagnetometer(tNanos: Long, value: Vec3) = enqueue(tNanos, value, gyroscope = false)

    /** El servidor usa el giroscopio para no detectar mientras se mueve el telefono. */
    override fun onGyroscope(tNanos: Long, value: Vec3) = enqueue(tNanos, value, gyroscope = true)

    private fun enqueue(tNanos: Long, value: Vec3, gyroscope: Boolean) {
        if (baseUrl.isEmpty()) return
        // event.timestamp es relativo al arranque: pasarlo a tiempo Unix.
        val offset = System.currentTimeMillis() * 1_000_000L - SystemClock.elapsedRealtimeNanos()
        synchronized(samples) {
            samples.addLast(SensorSample(tNanos + offset, value, gyroscope))
            while (samples.size > MAX_QUEUED_SAMPLES) samples.removeFirst()
        }
    }

    fun sendEvent(type: String, text: String, signal: Double? = null, cosine: Double? = null) {
        if (baseUrl.isEmpty()) return
        val json = SensorLoggerFormat.event(type, text, System.currentTimeMillis(), signal, cosine)
        synchronized(events) {
            events.addLast(json)
            while (events.size > MAX_QUEUED_EVENTS) events.removeFirst()
        }
    }

    private suspend fun flush() {
        val base = baseUrl
        if (base.isEmpty()) {
            synchronized(samples) { samples.clear() }
            synchronized(events) { events.clear() }
            return
        }
        if (SystemClock.elapsedRealtime() < backoffUntil) return

        val batch = synchronized(samples) { samples.toList().also { samples.clear() } }
        if (batch.isNotEmpty()) {
            val body = SensorLoggerFormat.batch(
                messageId = ++messageId,
                sessionId = sessionId,
                deviceId = DEVICE_ID,
                uncalibrated = SensorHub.snapshot.value.magUncalibrated,
                samples = batch,
            )
            if (!post("$base/data", body)) return
            _status.value = _status.value.copy(samplesSent = _status.value.samplesSent + batch.count { !it.gyroscope })
        }
        while (true) {
            val json = synchronized(events) { events.removeFirstOrNull() } ?: break
            if (!post("$base/app-event", json)) {
                synchronized(events) { events.addFirst(json) }
                return
            }
        }
    }

    private suspend fun post(url: String, json: String): Boolean =
        when (val r = Http.postJson(url, json)) {
            is Http.Result.Ok -> {
                if (!_status.value.connected) _status.value = _status.value.copy(connected = true, lastError = null)
                true
            }
            is Http.Result.Failed -> {
                _status.value = _status.value.copy(connected = false, lastError = r.reason)
                backoffUntil = SystemClock.elapsedRealtime() + BACKOFF_MS
                false
            }
        }

    private companion object {
        const val PERIOD_MS = 100L
        const val BACKOFF_MS = 2_000L
        const val MAX_QUEUED_SAMPLES = 4_000
        const val MAX_QUEUED_EVENTS = 50
        const val DEVICE_ID = "magnesense-android"
    }
}
