package cl.magnesense.remote

import android.os.SystemClock
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.util.concurrent.TimeUnit

/**
 * Conexion en vivo al /ws de server.py: estado de los detectores aprendidos y sus eventos.
 * Se reconecta sola. "Conectado" significa socket abierto y mensajes recientes (el servidor
 * emite uno por cada lote de telemetria, ~10 por segundo).
 */
class ServerSocket(scope: CoroutineScope) {

    private val client = OkHttpClient.Builder()
        .connectTimeout(3, TimeUnit.SECONDS)
        .pingInterval(10, TimeUnit.SECONDS)
        .build()

    private val _state = MutableStateFlow(ServerState())
    val state: StateFlow<ServerState> = _state.asStateFlow()

    private val _events = MutableSharedFlow<ServerEvent>(extraBufferCapacity = 64)
    val events: SharedFlow<ServerEvent> = _events.asSharedFlow()

    /** Ultimos eventos crudos, para la pantalla de depuracion. */
    private val _recentEvents = MutableStateFlow<List<ServerEvent>>(emptyList())
    val recentEvents: StateFlow<List<ServerEvent>> = _recentEvents.asStateFlow()

    @Volatile
    private var socket: WebSocket? = null

    @Volatile
    private var lastMessageMs = 0L

    @Volatile
    var baseUrl: String = ""
        set(value) {
            val clean = value.trim().trimEnd('/')
            if (clean == field) return
            field = clean
            reconnect()
        }

    init {
        scope.launch {
            while (isActive) {
                delay(CHECK_MS)
                if (baseUrl.isEmpty()) continue
                val fresh = socket != null && SystemClock.elapsedRealtime() - lastMessageMs < FRESH_MS
                if (fresh != _state.value.connected) _state.update { it.copy(connected = fresh) }
                if (socket == null) reconnect()
            }
        }
    }

    private fun reconnect() {
        socket?.cancel()
        socket = null
        val url = baseUrl
        if (url.isEmpty()) {
            _state.value = ServerState()
            return
        }
        val wsUrl = url.replaceFirst("https://", "wss://").replaceFirst("http://", "ws://") + "/ws"
        val request = runCatching { Request.Builder().url(wsUrl).build() }.getOrElse {
            _state.update { s -> s.copy(connected = false, error = "URL inválida") }
            return
        }
        socket = client.newWebSocket(request, Listener(url))
    }

    private inner class Listener(private val forUrl: String) : WebSocketListener() {
        override fun onMessage(webSocket: WebSocket, text: String) {
            if (forUrl != baseUrl) return
            lastMessageMs = SystemClock.elapsedRealtime()
            val m = ServerJson.parseMessage(text) ?: return
            _state.update { s ->
                s.copy(
                    connected = true,
                    error = null,
                    phase2 = m.phase2 ?: s.phase2,
                    recording = m.recording ?: s.recording,
                    examples = m.examples ?: s.examples,
                )
            }
            if (m.events.isNotEmpty()) {
                m.events.forEach { _events.tryEmit(it) }
                _recentEvents.update { (it + m.events).takeLast(RECENT_EVENTS) }
            }
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) = closed(webSocket, t.javaClass.simpleName)

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) = closed(webSocket, null)

        private fun closed(webSocket: WebSocket, error: String?) {
            if (socket === webSocket) socket = null
            _state.update { it.copy(connected = false, error = error) }
        }
    }

    private companion object {
        const val CHECK_MS = 1_000L
        const val FRESH_MS = 3_000L
        const val RECENT_EVENTS = 20
    }
}
