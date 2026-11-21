package cl.magnesense.ui.history

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import cl.magnesense.data.EventLog
import cl.magnesense.data.HistoryEntry
import cl.magnesense.data.HistoryKind
import cl.magnesense.ui.components.BigOutlineButton
import cl.magnesense.ui.components.Panel
import cl.magnesense.ui.theme.Palette
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

@Composable
fun HistoryScreen(log: EventLog) {
    val entries by log.entries.collectAsState()
    val format = SimpleDateFormat("dd/MM HH:mm:ss", Locale.forLanguageTag("es-CL"))
    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        item {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("Historial", style = MaterialTheme.typography.headlineMedium, color = Palette.Text)
            }
        }
        if (entries.isEmpty()) {
            item { Text("Todavía no hay eventos.", style = MaterialTheme.typography.bodyLarge, color = Palette.Muted) }
        }
        items(entries.asReversed()) { e -> Entry(e, format.format(Date(e.timeMs))) }
        if (entries.isNotEmpty()) {
            item { BigOutlineButton("Borrar historial", log::clear, Modifier.fillMaxWidth().padding(top = 8.dp)) }
        }
    }
}

@Composable
private fun Entry(e: HistoryEntry, time: String) {
    val (mark, color) = when (e.kind) {
        HistoryKind.ACTION -> "✓" to Palette.Ok
        HistoryKind.ACTIVATION -> "●" to Palette.Highlight
        HistoryKind.ACTION_FAILED, HistoryKind.WARNING -> "!" to Palette.Warning
        HistoryKind.IGNORED -> "×" to Palette.Muted
        HistoryKind.PAUSE -> "‖" to Palette.WarningSoft
        HistoryKind.CALIBRATION -> "◎" to Palette.Ok
    }
    Panel {
        Row {
            Text(mark, color = color, style = MaterialTheme.typography.titleLarge, modifier = Modifier.width(32.dp))
            Column {
                Text(e.text, color = Palette.Text, style = MaterialTheme.typography.bodyLarge)
                Text(time, color = Palette.Muted, style = MaterialTheme.typography.bodyMedium, fontFamily = FontFamily.Monospace)
            }
        }
    }
}
