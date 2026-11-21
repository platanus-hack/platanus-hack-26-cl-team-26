package cl.magnesense.data

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import org.json.JSONArray
import org.json.JSONObject

enum class HistoryKind { ACTIVATION, ACTION, ACTION_FAILED, IGNORED, PAUSE, WARNING, CALIBRATION }

data class HistoryEntry(val timeMs: Long, val kind: HistoryKind, val text: String)

/** Historial reciente (lo mas nuevo al final), guardado entre sesiones. */
class EventLog(context: Context, private val capacity: Int = 100) {

    private val prefs = context.getSharedPreferences("magnesense_history", Context.MODE_PRIVATE)

    private val _entries = MutableStateFlow(load())
    val entries: StateFlow<List<HistoryEntry>> = _entries.asStateFlow()

    fun add(kind: HistoryKind, text: String) {
        _entries.update { (it + HistoryEntry(System.currentTimeMillis(), kind, text)).takeLast(capacity) }
        save()
    }

    fun clear() {
        _entries.value = emptyList()
        save()
    }

    private fun save() {
        val arr = JSONArray(_entries.value.map { JSONObject().put("t", it.timeMs).put("k", it.kind.name).put("x", it.text) })
        prefs.edit().putString(KEY, arr.toString()).apply()
    }

    private fun load(): List<HistoryEntry> = runCatching {
        val arr = JSONArray(prefs.getString(KEY, "[]"))
        (0 until arr.length()).mapNotNull { i ->
            val o = arr.optJSONObject(i) ?: return@mapNotNull null
            val kind = runCatching { HistoryKind.valueOf(o.optString("k")) }.getOrNull() ?: return@mapNotNull null
            HistoryEntry(o.optLong("t"), kind, o.optString("x"))
        }
    }.getOrDefault(emptyList())

    private companion object {
        const val KEY = "history_v1"
    }
}
