package cl.magnesense.remote

import cl.magnesense.actions.Http
import org.json.JSONObject

/**
 * Llamadas a la fase 2 de server.py: grabar ejemplos, crear y borrar detectores.
 * Nunca lanza excepciones: los errores vuelven como texto para mostrar.
 */
class ServerApi(private val baseUrl: () -> String) {

    sealed interface Outcome<out T> {
        data class Ok<T>(val value: T) : Outcome<T>
        data class Error(val message: String) : Outcome<Nothing>
    }

    suspend fun startRecording(label: String): Outcome<Unit> =
        post("/record/start", JSONObject().put("label", label).toString()) { }

    /** Devuelve cuantos ejemplos hay ahora de esa etiqueta. */
    suspend fun stopRecording(): Outcome<Int> = post("/record/stop", "{}") { JSONObject(it).optInt("examples") }

    suspend fun clearExamples(label: String): Outcome<Unit> =
        post("/examples/clear", JSONObject().put("label", label).toString()) { }

    suspend fun train(request: TrainRequest): TrainResult {
        val base = baseUrl().ifEmpty { return TrainResult(ok = false, error = NO_SERVER) }
        return when (val r = Http.postJson("$base/train", ServerJson.trainBody(request), TRAIN_TIMEOUT_MS)) {
            is Http.Result.Ok -> ServerJson.parseTrain(r.body)
            is Http.Result.Failed ->
                if (r.body.isNotBlank()) ServerJson.parseTrain(r.body) else TrainResult(ok = false, error = r.reason)
        }
    }

    suspend fun removeDetector(name: String): Outcome<Unit> =
        post("/detectors/remove", JSONObject().put("name", name).toString()) { }

    sealed interface AgentOutcome {
        data class Reply(val reply: AgentReply) : AgentOutcome
        /** El servidor no tiene POST /agent todavia. */
        data object NotAvailable : AgentOutcome
        data class Error(val message: String) : AgentOutcome
    }

    /** Pide al asistente (Claude, en el servidor) que entienda un pedido en lenguaje natural. */
    suspend fun askAgent(body: String): AgentOutcome {
        val base = baseUrl().ifEmpty { return AgentOutcome.Error(NO_SERVER) }
        return when (val r = Http.postJson("$base/agent", body, AGENT_TIMEOUT_MS)) {
            is Http.Result.Ok -> ServerJson.parseAgent(r.body)?.let { AgentOutcome.Reply(it) }
                ?: AgentOutcome.Error("Respuesta inválida del asistente")
            is Http.Result.Failed -> when (r.code) {
                404, 405 -> AgentOutcome.NotAvailable
                else -> AgentOutcome.Error(
                    runCatching { JSONObject(r.body).optString("error") }.getOrNull()?.ifBlank { null } ?: r.reason,
                )
            }
        }
    }

    private suspend fun <T> post(path: String, json: String, parse: (String) -> T): Outcome<T> {
        val base = baseUrl().ifEmpty { return Outcome.Error(NO_SERVER) }
        return when (val r = Http.postJson("$base$path", json)) {
            is Http.Result.Ok -> runCatching { Outcome.Ok(parse(r.body)) }.getOrElse { Outcome.Error("Respuesta inválida") }
            is Http.Result.Failed -> Outcome.Error(
                runCatching { JSONObject(r.body).optString("error") }.getOrNull()?.ifBlank { null } ?: r.reason,
            )
        }
    }

    companion object {
        const val NO_SERVER = "Falta la URL del servidor (Ajustes → Servidor)"
        private const val TRAIN_TIMEOUT_MS = 8_000
        /** Un modelo de lenguaje puede tardar varios segundos. */
        private const val AGENT_TIMEOUT_MS = 30_000
    }
}
