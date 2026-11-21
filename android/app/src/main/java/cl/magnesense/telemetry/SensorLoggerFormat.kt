package cl.magnesense.telemetry

import cl.magnesense.detector.Vec3
import java.util.Locale

/** Una lectura lista para enviar; [epochNanos] en tiempo Unix (ns). */
data class SensorSample(val epochNanos: Long, val value: Vec3, val gyroscope: Boolean = false)

/**
 * Construye el JSON de "HTTP Push" de la app Sensor Logger, que server.py ya entiende
 * (magnetometro y giroscopio, este ultimo con "name":"gyroscope"):
 * {"messageId":1,"sessionId":"..","deviceId":"..","payload":[{"name":"magnetometeruncalibrated",
 *   "time":1700000000000000000,"values":{"x":..,"y":..,"z":..}}]}
 * Sin dependencias de Android para poder probarlo.
 */
object SensorLoggerFormat {

    fun batch(messageId: Long, sessionId: String, deviceId: String, uncalibrated: Boolean, samples: List<SensorSample>): String {
        val magName = if (uncalibrated) "magnetometeruncalibrated" else "magnetometer"
        val sb = StringBuilder(64 + samples.size * 110)
        sb.append("{\"messageId\":").append(messageId)
            .append(",\"sessionId\":\"").append(escape(sessionId))
            .append("\",\"deviceId\":\"").append(escape(deviceId))
            .append("\",\"payload\":[")
        samples.forEachIndexed { i, s ->
            if (i > 0) sb.append(',')
            sb.append("{\"name\":\"").append(if (s.gyroscope) "gyroscope" else magName)
                .append("\",\"time\":").append(s.epochNanos)
                .append(",\"values\":{\"x\":").append(num(s.value.x))
                .append(",\"y\":").append(num(s.value.y))
                .append(",\"z\":").append(num(s.value.z))
                .append("}}")
        }
        return sb.append("]}").toString()
    }

    /** Evento de la app para POST /app-event. */
    fun event(type: String, text: String, epochMs: Long, signal: Double? = null, cosine: Double? = null): String {
        val sb = StringBuilder("{\"type\":\"").append(escape(type))
            .append("\",\"text\":\"").append(escape(text))
            .append("\",\"time\":").append(epochMs)
        if (signal != null && signal.isFinite()) sb.append(",\"signal\":").append(num(signal))
        if (cosine != null && cosine.isFinite()) sb.append(",\"cosine\":").append(num(cosine))
        return sb.append('}').toString()
    }

    private fun num(v: Double): String = if (v.isFinite()) String.format(Locale.US, "%.4f", v) else "0"

    private fun escape(s: String): String = buildString(s.length) {
        for (c in s) {
            when {
                c == '"' -> append("\\\"")
                c == '\\' -> append("\\\\")
                c == '\n' -> append("\\n")
                c < ' ' -> append(String.format(Locale.US, "\\u%04x", c.code))
                else -> append(c)
            }
        }
    }
}
