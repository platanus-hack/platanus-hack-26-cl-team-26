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
    }
}
