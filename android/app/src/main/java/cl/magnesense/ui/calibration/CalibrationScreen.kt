package cl.magnesense.ui.calibration

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import cl.magnesense.detector.Detector
import cl.magnesense.detector.DetectorState
import cl.magnesense.detector.DetectorStatus
import cl.magnesense.detector.MagnetCalibration
import cl.magnesense.ui.components.BigButton
import cl.magnesense.ui.components.BigOutlineButton
import cl.magnesense.ui.components.Panel
import cl.magnesense.ui.components.ScreenColumn
import cl.magnesense.ui.components.SignalMeter
import cl.magnesense.ui.theme.Palette
import kotlin.math.max

private enum class Step { INTRO, REST, MAGNET, RESULT }

/**
 * Asistente de calibracion en dos pasos. Lo usa el cuidador; la persona solo
 * mantiene la mano quieta y luego acerca el iman cinco veces.
 */
@Composable
fun CalibrationScreen(detector: Detector, onDone: () -> Unit) {
    val status by detector.status.collectAsState()
    var step by remember { mutableStateOf(Step.INTRO) }

    // Avanza solo cuando el detector termina cada fase.
    LaunchedEffect(step, status.state) {
        when {
            step == Step.REST && status.state == DetectorState.REST -> {
                detector.startMagnetCalibration()
                step = Step.MAGNET
            }
            step == Step.MAGNET && status.state == DetectorState.REST && status.magnet != null -> step = Step.RESULT
        }
    }

    Column(Modifier.verticalScroll(rememberScrollState())) {
        ScreenColumn {
            when (step) {
                Step.INTRO -> Intro(
                    hasCalibration = status.isCalibrated,
                    onStart = {
                        detector.startRestCalibration()
                        step = Step.REST
                    },
                )
                Step.REST -> RestStep(status) {
                    detector.cancelCalibration()
                    step = Step.INTRO
                }
                Step.MAGNET -> MagnetStep(status, required = detector.config.magnetPeaksRequired) {
                    detector.cancelCalibration()
                    step = Step.INTRO
                }
                Step.RESULT -> ResultStep(
                    magnet = status.magnet!!,
                    restThreshold = max(detector.config.kSigma * status.noise, detector.config.minOnThreshold),
                    onThreshold = status.onThreshold,
                    onRepeat = {
                        detector.startRestCalibration()
                        step = Step.REST
                    },
                    onContinue = {
                        step = Step.INTRO
                        onDone()
                    },
                )
            }
        }
    }
}

@Composable
private fun Intro(hasCalibration: Boolean, onStart: () -> Unit) {
    Title("Calibración")
    Panel {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Body("1. Deja el celular sobre una superficie firme y la mano quieta, sin el imán cerca, durante 10 segundos.")
            Body("2. Luego acerca el imán 5 veces, con el mismo movimiento que usarás para activar.")
            if (hasCalibration) Muted("Ya hay una calibración guardada. Repetirla es buena idea si cambiaste de lugar o de imán.")
        }
    }
    BigButton("Empezar", onStart, Modifier.fillMaxWidth())
}

@Composable
private fun RestStep(status: DetectorStatus, onCancel: () -> Unit) {
    Title("Paso 1 de 2: quieto")
    Panel {
        Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Body("No muevas el celular ni el imán. Estamos midiendo el campo del lugar.")
            LinearProgressIndicator(
                progress = { status.progress.toFloat() },
                modifier = Modifier.fillMaxWidth().height(18.dp),
                color = Palette.Highlight,
                trackColor = Palette.Border,
            )
            val remaining = ((1 - status.progress) * 10).toInt() + 1
            Body(if (status.progress < 1) "Faltan $remaining s" else "Listo")
            if (!status.gyroOk) Warning("El celular se movió: empezamos de nuevo.")
        }
    }
    BigOutlineButton("Cancelar", onCancel, Modifier.fillMaxWidth())
}

@Composable
private fun MagnetStep(status: DetectorStatus, required: Int, onCancel: () -> Unit) {
    val done = status.magnetPeaks.size
    Title("Paso 2 de 2: acerca el imán")
    Panel {
        Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
            Body("Acerca el imán y aléjalo. Repite $required veces, siempre con el mismo movimiento.")
            Row(horizontalArrangement = Arrangement.spacedBy(14.dp), verticalAlignment = Alignment.CenterVertically) {
                repeat(required) { i -> Dot(filled = i < done) }
            }
            Body("$done de $required")
            SignalMeter(status.signal, status.peakThreshold)
            Muted("Cada acercamiento debe pasar la marca ámbar (%.1f µT). Si no llega, bájala en Debug → Ajuste fino.".format(status.peakThreshold))
        }
    }
    BigOutlineButton("Cancelar", onCancel, Modifier.fillMaxWidth())
}

@Composable
private fun ResultStep(
    magnet: MagnetCalibration,
    restThreshold: Double,
    onThreshold: Double,
    onRepeat: () -> Unit,
    onContinue: () -> Unit,
) {
    val ratio = magnet.medianPeak / restThreshold
    val (signalText, signalOk) = when {
        ratio >= 4 -> "Señal fuerte" to true
        ratio >= 2 -> "Señal aceptable" to true
        else -> "Señal débil: acerca más el imán o usa uno más fuerte" to false
    }
    val (consistencyText, consistencyOk) = when {
        magnet.consistency >= 0.9 -> "Muy consistente: siempre acercaste el imán igual" to true
        magnet.consistency >= 0.6 -> "Consistente" to true
        else -> "Movimiento variable: aceptaremos más ángulos, pero también es más fácil activar sin querer" to false
    }
    Title("Resultado")
    Panel {
        Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            ResultLine(signalText, signalOk)
            ResultLine(consistencyText, consistencyOk)
            Muted("Pico típico %.1f µT · umbral de activación %.1f µT".format(magnet.medianPeak, onThreshold))
        }
    }
    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        BigOutlineButton("Repetir", onRepeat, Modifier.weight(1f))
        BigButton("Continuar", onContinue, Modifier.weight(1f))
    }
}

@Composable
private fun ResultLine(text: String, ok: Boolean) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(
            if (ok) "✓ " else "! ",
            color = if (ok) Palette.Ok else Palette.Warning,
            style = MaterialTheme.typography.titleLarge,
        )
        Text(text, color = Palette.Text, style = MaterialTheme.typography.bodyLarge)
    }
}

@Composable
private fun Dot(filled: Boolean) {
    Box(
        Modifier
            .size(40.dp)
            .background(if (filled) Palette.Highlight else Palette.Background, CircleShape)
            .border(3.dp, if (filled) Palette.Highlight else Palette.Border, CircleShape),
    )
}

@Composable
private fun Title(text: String) =
    Text(text, style = MaterialTheme.typography.headlineMedium, color = Palette.Text, modifier = Modifier.padding(top = 4.dp))

@Composable
private fun Body(text: String) = Text(text, style = MaterialTheme.typography.bodyLarge, color = Palette.Text)

@Composable
private fun Muted(text: String) = Text(text, style = MaterialTheme.typography.bodyMedium, color = Palette.Muted)

@Composable
private fun Warning(text: String) = Text(text, style = MaterialTheme.typography.bodyLarge, color = Palette.WarningSoft)
