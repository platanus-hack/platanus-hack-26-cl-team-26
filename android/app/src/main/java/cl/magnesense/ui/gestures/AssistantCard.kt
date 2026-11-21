package cl.magnesense.ui.gestures

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import cl.magnesense.MagneSenseApp
import cl.magnesense.ui.components.Panel
import cl.magnesense.ui.theme.Palette

/** Asistente de configuracion en lenguaje natural (se completa en el siguiente paso). */
@Composable
@Suppress("UNUSED_PARAMETER")
fun AssistantCard(app: MagneSenseApp, onTeach: (TeachDraft) -> Unit) {
    Panel {
        Text("Asistente: próximamente", style = MaterialTheme.typography.titleMedium, color = Palette.Muted)
    }
}
