package cl.magnesense.ui.debug

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableDoubleStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import cl.magnesense.data.DetectionTuning
import cl.magnesense.data.SettingsStore
import cl.magnesense.detector.DetectorStatus
import cl.magnesense.ui.components.AppSlider
import cl.magnesense.ui.components.BigOutlineButton
import cl.magnesense.ui.components.Panel
import cl.magnesense.ui.components.SectionTitle
import cl.magnesense.ui.components.Toggle
import cl.magnesense.ui.theme.Palette
import java.util.Locale
import kotlin.math.acos
import kotlin.math.max
import kotlin.math.roundToInt

/**
 * Ajuste fino en vivo: cuanta fuerza necesita el iman para calibrar y para activar.
 * Los cambios se guardan y se aplican al momento (los de calibracion, en la proxima calibracion).
 */
@Composable
fun TuningPanel(d: DetectorStatus, store: SettingsStore) {
    val settings by store.settings.collectAsState()
    val t = settings.tuning
    fun set(transform: (DetectionTuning) -> DetectionTuning) = store.update { it.copy(tuning = transform(it.tuning)) }

    // Maximo de la senal para ver cuanto alcanza el movimiento real.
    var peak by remember { mutableDoubleStateOf(0.0) }
    LaunchedEffect(d.signal) { peak = max(peak, d.signal) }

    Panel {
        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            SectionTitle("Ajuste fino del imán")
            Line("Señal ahora %.1f µT · máximo %.1f µT".format(Locale.US, d.signal, peak))
            BigOutlineButton("Reiniciar máximo", { peak = 0.0 }, Modifier.fillMaxWidth())

            Header("Calibración: cada acercamiento debe superar %.1f µT".format(Locale.US, d.peakThreshold))
            Hint("= el mayor entre %.1f × ruido σ (%.2f µT) y el mínimo absoluto.".format(Locale.US, t.peakMinSigma, d.noise))
            Line("Mínimo absoluto: %.1f µT".format(Locale.US, t.peakMin))
            AppSlider(t.peakMin.toFloat(), 0.5f..10f, steps = 18) { v -> set { it.copy(peakMin = snap(v, 0.5)) } }
            Line("Multiplicador del ruido: ×%.0f".format(Locale.US, t.peakMinSigma))
            AppSlider(t.peakMinSigma.toFloat(), 2f..12f, steps = 9) { v -> set { it.copy(peakMinSigma = snap(v, 1.0)) } }
            Hint("Bájalos si el imán es débil y los puntos no se llenan. Después vuelve a calibrar.")

            Header("Activación: superar %.1f µT (suelta bajo %.1f µT)".format(Locale.US, d.onThreshold, d.offThreshold))
            Line("Fracción del pico calibrado: %.2f".format(Locale.US, t.peakFraction))
            AppSlider(t.peakFraction.toFloat(), 0.2f..0.8f, steps = 11) { v -> set { it.copy(peakFraction = snap(v, 0.05)) } }
            Line("Multiplicador del ruido: ×%.1f".format(Locale.US, t.kSigma))
            AppSlider(t.kSigma.toFloat(), 2f..10f, steps = 15) { v -> set { it.copy(kSigma = snap(v, 0.5)) } }
            Line("Piso del umbral: %.1f µT".format(Locale.US, t.minOn))
            AppSlider(t.minOn.toFloat(), 0.2f..5f, steps = 23) { v -> set { it.copy(minOn = snap(v, 0.2)) } }
            Header("Dirección")
            Toggle("Comprobar dirección", t.directionCheck) { v -> set { it.copy(directionCheck = v) } }
            if (t.directionCheck) {
                Line(
                    if (d.directionCheck) {
                        "Se exige cos ≥ %.2f (±%.0f°) · ahora %s".format(
                            Locale.US, d.minCosine, Math.toDegrees(acos(d.minCosine.coerceIn(-1.0, 1.0))),
                            if (d.cosine.isNaN()) "-" else "%.2f".format(Locale.US, d.cosine),
                        )
                    } else {
                        "Sin imán calibrado: no se revisa"
                    },
                )
                Line("Dirección mínima (coseno): %.2f".format(Locale.US, t.minCosine))
                AppSlider(t.minCosine.toFloat(), 0f..0.95f, steps = 18) { v -> set { it.copy(minCosine = snap(v, 0.05)) } }
                Hint("Si los acercamientos de la calibración variaron más, se usa un cono más ancho automáticamente.")
                Toggle("Aceptar el imán dado vuelta", t.acceptReversed) { v -> set { it.copy(acceptReversed = v) } }
            } else {
                Hint("Cualquier campo fuerte activa, también otros metales o imanes.")
            }

            Row { BigOutlineButton("Restablecer valores", { set { DetectionTuning() } }, Modifier.fillMaxWidth()) }
        }
    }
}

private fun snap(v: Float, step: Double): Double = (v / step).roundToInt() * step

@Composable
private fun Header(text: String) =
    Text(text, style = MaterialTheme.typography.titleMedium, color = Palette.Highlight)

@Composable
private fun Line(text: String) = Text(text, style = MaterialTheme.typography.bodyLarge, color = Palette.Text)

@Composable
private fun Hint(text: String) = Text(text, style = MaterialTheme.typography.bodyMedium, color = Palette.Muted)
