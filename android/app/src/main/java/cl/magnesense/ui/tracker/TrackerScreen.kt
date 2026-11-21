package cl.magnesense.ui.tracker

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import cl.magnesense.MagneSenseApp
import cl.magnesense.tracking.LiveTracker
import cl.magnesense.tracking.TrackState
import cl.magnesense.tracking.TrackerException
import cl.magnesense.tracking.TrackerUiState
import cl.magnesense.ui.components.AppSlider
import cl.magnesense.ui.components.BigButton
import cl.magnesense.ui.components.BigOutlineButton
import cl.magnesense.ui.components.Panel
import cl.magnesense.ui.gestures.Choice
import cl.magnesense.ui.gestures.ChoiceRow
import cl.magnesense.ui.theme.Palette
import java.util.Locale

/**
 * Pestana 3D: calibracion en dos pasos, la posicion del iman en vivo y dibujar con el dedo.
 * Sin desplazamiento vertical para que arrastrar sobre la vista gire la camara.
 */
@Composable
fun TrackerScreen(app: MagneSenseApp) {
    val ui by app.tracker.state.collectAsState()
    var view by rememberSaveable { mutableStateOf(VIEW_3D) }
    var showCalibration by rememberSaveable { mutableStateOf(true) }

    Column(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        if (!ui.calibrated || showCalibration) {
            CalibrationPanel(app.tracker, ui, onDone = { showCalibration = false })
        } else {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(
                    "Calibrado a %.1f cm".format(Locale.US, ui.refCm ?: 0.0),
                    style = MaterialTheme.typography.bodyLarge,
                    color = Palette.Muted,
                    modifier = Modifier.weight(1f),
                )
                BigOutlineButton("Recalibrar", { showCalibration = true })
            }
        }
        StatusLine(ui)
        if (ui.calibrated && !showCalibration) {
            ChoiceRow(listOf(Choice(VIEW_3D, "Vista 3D"), Choice(VIEW_DRAW, "Dibujar")), view) { view = it }
            if (view == VIEW_3D) {
                Tracker3DView(ui, Modifier.fillMaxWidth().weight(1f))
                Readouts(ui)
            } else {
                TrackerDrawView(ui, Modifier.fillMaxWidth().weight(1f))
            }
        }
    }
}

@Composable
private fun CalibrationPanel(tracker: LiveTracker, ui: TrackerUiState, onDone: () -> Unit) {
    var distCm by remember { mutableFloatStateOf(3f) }
    var message by remember { mutableStateOf<String?>(null) }
    var ok by remember { mutableStateOf(true) }
    Panel {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("Posición 3D del imán", style = MaterialTheme.typography.headlineMedium, color = Palette.Text)
            Text(
                "El imán debe mirar siempre hacia el mismo lado (pegado en la uña o en un anillo). El celular, quieto.",
                style = MaterialTheme.typography.bodyMedium,
                color = Palette.Muted,
            )
            Text(
                (if (ui.hasBase) "✓ " else "1. ") + "Aleja el imán más de 30 cm",
                style = MaterialTheme.typography.titleMedium,
                color = if (ui.hasBase) Palette.Ok else Palette.Text,
            )
            BigOutlineButton("Medir sin imán", {
                val error = tracker.measureBase()
                ok = error == null
                message = error ?: "Listo: ahora el paso 2."
            }, Modifier.fillMaxWidth())
            Text(
                "2. Pon el imán justo sobre el sensor, a %.1f cm, mirando como lo vas a usar".format(Locale.US, distCm),
                style = MaterialTheme.typography.titleMedium,
                color = Palette.Text,
            )
            AppSlider(distCm, 1f..10f, steps = 17) { distCm = (it * 2).toInt() / 2f }
            BigButton("Calibrar imán", {
                try {
                    val cal = tracker.calibrate(distCm.toDouble())
                    ok = true
                    message = "Imán: %.3f A·m², inclinación %.0f°, campo %.0f µT"
                        .format(Locale.US, cal.momentAm2, cal.tiltDegrees, cal.fieldUt)
                    onDone()
                } catch (e: TrackerException) {
                    ok = false
                    message = e.message
                }
            }, Modifier.fillMaxWidth(), enabled = ui.hasBase)
            message?.let {
                Text(
                    (if (ok) "✓ " else "! ") + it,
                    style = MaterialTheme.typography.bodyLarge,
                    color = if (ok) Palette.Ok else Palette.WarningSoft,
                )
            }
        }
    }
}

@Composable
private fun StatusLine(ui: TrackerUiState) {
    val r = ui.result
    val (text, color) = when {
        ui.phoneMoving -> "Celular moviéndose: déjalo quieto" to Palette.Warning
        r.state == TrackState.NO_BASE -> "Falta el paso 1 (medir sin imán)" to Palette.Muted
        r.state == TrackState.NO_MAGNET -> "Falta el paso 2 (calibrar el imán)" to Palette.Muted
        r.state == TrackState.FAR -> "Imán lejos (%.1f µT): acércalo".format(Locale.US, r.fieldUt) to Palette.Muted
        r.confidence >= 0.8 -> "Rastreando · el modelo calza bien (%.2f)".format(Locale.US, r.confidence) to confidenceColor(r.confidence)
        r.confidence >= 0.5 -> "Rastreando · calce regular (%.2f)".format(Locale.US, r.confidence) to confidenceColor(r.confidence)
        else -> "Calce bajo (%.2f): ¿se inclinó el imán o hay metal cerca?".format(Locale.US, r.confidence) to confidenceColor(r.confidence)
    }
    Text(text, style = MaterialTheme.typography.titleMedium, color = color)
    if (ui.calibrated && ui.rejected > 0) {
        Text(
            "Saltos descartados: ${ui.rejected}. Si son muchos: no gires el imán en el dedo, " +
                "mantenlo entre 2 y 6 cm del sensor, o recalibra.",
            style = MaterialTheme.typography.bodyMedium,
            color = Palette.Muted,
        )
    }
}

@Composable
private fun Readouts(ui: TrackerUiState) {
    val p = ui.display
    val values = if (ui.result.state == TrackState.TRACKING && p != null) {
        listOf(
            "x" to "%.1f".format(Locale.US, p.x),
            "y" to "%.1f".format(Locale.US, p.y),
            "z" to "%.1f".format(Locale.US, p.z),
            "dist" to "%.1f".format(Locale.US, ui.result.distCm),
        )
    } else {
        listOf("x" to "–", "y" to "–", "z" to "–", "dist" to "–")
    }
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        for ((label, value) in values) {
            Column {
                Text(label, style = MaterialTheme.typography.bodyMedium, color = Palette.Muted)
                Text("$value cm", style = MaterialTheme.typography.titleMedium, color = Palette.Text)
            }
        }
    }
}

private const val VIEW_3D = "3d"
private const val VIEW_DRAW = "draw"
