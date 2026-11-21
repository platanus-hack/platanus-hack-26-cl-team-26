package cl.magnesense.remote

import org.json.JSONArray
import org.json.JSONObject

/**
 * Lectura de los mensajes de server.py. Tolerante: lo que falte o venga con otra forma
 * se ignora en vez de botar la app (el servidor cambia rapido durante la hackathon).
 */
object ServerJson {

    /** Un mensaje del WebSocket /ws ya interpretado. */
    data class Message(
        val phase2: ServerPhase2?,
        val recording: String?,
        val examples: Map<String, Int>?,
        val events: List<ServerEvent>,
    )

    fun parseMessage(text: String): Message? {
        val o = runCatching { JSONObject(text) }.getOrNull() ?: return null
        val type = o.optString("type")
        if (type != "state" && type != "data") return null
        return Message(
            phase2 = o.optJSONObject("phase2")?.let(::parsePhase2),
            recording = if (o.has("recording")) o.optString("recording") else null,
            examples = o.optJSONObject("examples")?.let(::parseCounts),
            events = o.optJSONArray("events2")?.let(::parseEvents).orEmpty(),
        )
    }

    fun parsePhase2(o: JSONObject) = ServerPhase2(
        calibrating = o.optBoolean("calibrating"),
        noise = o.optDouble("noise", 0.0).takeIf { it.isFinite() } ?: 0.0,
        gyro = o.optBoolean("gyro"),
        phoneMoving = o.optBoolean("phone_moving"),
        detectors = o.optJSONArray("detectors")?.let { arr ->
            (0 until arr.length()).mapNotNull { arr.optJSONObject(it)?.let(::parseDetector) }
        }.orEmpty(),
    )

    private fun parseDetector(o: JSONObject): RemoteDetector? {
        val name = o.optString("name").ifBlank { return null }
        val type = DetectorType.fromWire(o.optString("type")) ?: return null
        return RemoteDetector(
            name = name,
            type = type,
            trigger = o.optString("trigger"),
            active = o.optBoolean("active"),
            count = o.optInt("count"),
            labels = o.optJSONArray("labels")?.let(::strings).orEmpty(),
            state = o.optString("state").takeIf { o.has("state") && !o.isNull("state") },
        )
    }

    private fun parseEvents(arr: JSONArray): List<ServerEvent> = (0 until arr.length()).mapNotNull { i ->
        val e = arr.optJSONObject(i) ?: return@mapNotNull null
        val detector = e.optString("detector").ifBlank { return@mapNotNull null }
        ServerEvent(
            detector = detector,
            kind = e.optString("kind"),
            t = e.optDouble("t", 0.0),
            state = e.optString("state").takeIf { e.has("state") && !e.isNull("state") },
            duration = e.optDouble("duration").takeIf { e.has("duration") && it.isFinite() },
        )
    }

    fun parseCounts(o: JSONObject): Map<String, Int> = o.keys().asSequence().associateWith { o.optInt(it) }

    fun parseTrain(body: String): TrainResult {
        val o = runCatching { JSONObject(body) }.getOrNull()
            ?: return TrainResult(ok = false, error = "Respuesta inválida del servidor")
        if (!o.optBoolean("ok")) return TrainResult(ok = false, error = o.optString("error", "No se pudo crear"))
        val info = o.optJSONObject("info")
        return TrainResult(
            ok = true,
            detector = o.optString("detector"),
            consistency = info?.optDouble("consistency")?.takeIf { info.has("consistency") && it.isFinite() },
            separation = info?.optDouble("separation")?.takeIf { info.has("separation") && it.isFinite() },
        )
    }

    fun trainBody(r: TrainRequest): String {
        val o = JSONObject()
            .put("type", r.type.wire)
            .put("name", r.name)
            // La app ejecuta la accion; el servidor solo detecta.
            .put("action", "none")
        r.label?.let { o.put("label", it) }
        if (r.labels.isNotEmpty()) o.put("labels", JSONArray(r.labels))
        r.trigger?.let { o.put("trigger", it) }
        return o.toString()
    }

    private fun strings(a: JSONArray) = (0 until a.length()).map { a.optString(it) }
}
