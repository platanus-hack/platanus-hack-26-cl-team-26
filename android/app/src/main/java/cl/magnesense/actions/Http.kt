package cl.magnesense.actions

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.HttpURLConnection
import java.net.URL

/** HTTP minimo para la red local. Nunca lanza excepciones: devuelve el codigo o un error. */
object Http {

    const val TIMEOUT_MS = 2_000

    sealed interface Result {
        data class Ok(val code: Int) : Result
        data class Failed(val reason: String) : Result
    }

    suspend fun get(url: String, timeoutMs: Int = TIMEOUT_MS): Result = request(url, "GET", null, timeoutMs)

    suspend fun postJson(url: String, json: String, timeoutMs: Int = TIMEOUT_MS): Result =
        request(url, "POST", json, timeoutMs)

    private suspend fun request(url: String, method: String, json: String?, timeoutMs: Int): Result =
        withContext(Dispatchers.IO) {
            var conn: HttpURLConnection? = null
            try {
                conn = (URL(url).openConnection() as HttpURLConnection).apply {
                    requestMethod = method
                    connectTimeout = timeoutMs
                    readTimeout = timeoutMs
                    useCaches = false
                    if (json != null) {
                        doOutput = true
                        setRequestProperty("Content-Type", "application/json")
                    }
                }
                if (json != null) conn.outputStream.use { it.write(json.toByteArray()) }
                val code = conn.responseCode
                // Consumir la respuesta permite reutilizar la conexion.
                runCatching { (if (code < 400) conn.inputStream else conn.errorStream)?.use { it.readBytes() } }
                if (code in 200..299) Result.Ok(code) else Result.Failed("HTTP $code")
            } catch (e: Exception) {
                Result.Failed(e.javaClass.simpleName)
            } finally {
                conn?.disconnect()
            }
        }
}
