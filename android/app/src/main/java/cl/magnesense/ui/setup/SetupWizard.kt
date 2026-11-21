package cl.magnesense.ui.setup

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableDoubleStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import cl.magnesense.MagneSenseApp
import cl.magnesense.data.ActivationMode
import cl.magnesense.data.AppSettings
import cl.magnesense.ui.components.BigButton
import cl.magnesense.ui.components.BigOutlineButton
import cl.magnesense.ui.components.ConditionChip
import cl.magnesense.ui.components.Panel
import cl.magnesense.ui.components.ScreenColumn
import cl.magnesense.ui.components.SignalMeter
import cl.magnesense.ui.gestures.TeachDraft
import cl.magnesense.ui.gestures.TeachGestureFlow
import cl.magnesense.ui.theme.Palette
import kotlinx.coroutines.delay
import java.util.Locale

private enum class SetupStep { WELCOME, PLACE, CALIBRATE, SONG, QUACK_INTRO, QUACK, DONE }

/**
 * Asistente de inicio: ubicar el iman, recalibrar, ensenar un gesto para la cancion y otro
 * para el cuack, y dejar activos los gestos aprendidos. Solo hace falta el celular y el iman.
 */
@Composable
fun SetupWizard(app: MagneSenseApp, onDone: () -> Unit) {
    var step by rememberSaveable { mutableStateOf(SetupStep.WELCOME) }

    // Mientras se ensena, el iman no debe armar el escaneo.
    DisposableEffect(Unit) {
        app.gestures.teaching = true
        onDispose { app.gestures.teaching = false }
    }

    when (step) {
        SetupStep.SONG -> TeachGestureFlow(
            app,
            TeachDraft(name = SONG_GESTURE, target = AppSettings.BIND_SONG),
            onClose = { step = SetupStep.QUACK_INTRO },
        )
        SetupStep.QUACK -> TeachGestureFlow(
            app,
            TeachDraft(name = QUACK_GESTURE, target = AppSettings.BIND_QUACK),
            onClose = { step = SetupStep.DONE },
        )
        else -> Column(Modifier.verticalScroll(rememberScrollState())) {
            ScreenColumn {
                Text("Primeros pasos", style = MaterialTheme.typography.headlineMedium, color = Palette.Text)
                Text(
                    "Paso ${step.ordinal + 1} de ${SetupStep.entries.size}",
                    style = MaterialTheme.typography.bodyMedium,
                    color = Palette.Muted,
                )
                when (step) {
                    SetupStep.WELCOME -> Welcome(onNext = { step = SetupStep.PLACE }, onSkip = onDone)
                    SetupStep.PLACE -> PlaceMagnet(app, onBack = { step = SetupStep.WELCOME }, onNext = { step = SetupStep.CALIBRATE })
                    SetupStep.CALIBRATE -> Calibrate(app, onBack = { step = SetupStep.PLACE }, onNext = { step = SetupStep.SONG })
                    SetupStep.QUACK_INTRO -> QuackIntro(onTeach = { step = SetupStep.QUACK }, onSkip = { step = SetupStep.DONE })
                    SetupStep.DONE -> Done(app, onDone)
                    else -> Unit
                }
            }
        }
    }
}

@Composable
private fun Welcome(onNext: () -> Unit, onSkip: () -> Unit) {
    Panel {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Body("Solo necesitas este celular y un imán pequeño. Toma unos 2 minutos.")
            Body("1. Ubicar el imán cerca del sensor.\n2. Calibrar el reposo.\n3. Enseñar un gesto para la canción (3 ejemplos).\n4. Si quieres, otro gesto para el cuack.")
            Body("Todo queda guardado en el celular: no hace falta servidor ni internet.")
        }
    }
    BigButton("Empezar", onNext, Modifier.fillMaxWidth())
    BigOutlineButton("Saltar por ahora", onSkip, Modifier.fillMaxWidth())
}

@Composable
private fun PlaceMagnet(app: MagneSenseApp, onBack: () -> Unit, onNext: () -> Unit) {
    val live by app.localGestures.live.collectAsState()
    val detector by app.engine.detector.status.collectAsState()
    // Pico de los ultimos segundos, para que el valor no salte tanto.
    var peak by remember { mutableDoubleStateOf(0.0) }
    LaunchedEffect(Unit) {
        while (true) {
            peak = maxOf(app.localGestures.live.value.signal, peak * PEAK_DECAY)
            delay(TICK_MS)
        }
    }
    val verdict = when {
        live.calibrating -> "Midiendo el reposo… deja el celular quieto." to Palette.Muted
        detector.saturated -> "Demasiado cerca: el sensor se satura. Aléjalo un poco." to Palette.WarningSoft
        peak < WEAK_UT -> "Acerca el imán al sensor hasta que la barra suba." to Palette.Muted
        peak < GOOD_UT -> "Se nota, pero débil (%.1f µT). Acércalo un poco más.".format(Locale.US, peak) to Palette.WarningSoft
        else -> "✓ Bien: %.0f µT, muy sobre el ruido.".format(Locale.US, peak) to Palette.Ok
    }

    Panel {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Title("Ubica el imán")
            Body("Deja el celular fijo (en la mesa o en un soporte). Pega el imán al dedo con cinta médica.")
            Body("El sensor suele estar arriba, cerca de la cámara. Mueve el imán por el borde y busca dónde sube más la barra. Para gestos, deja el dedo a 2–3 cm de ese punto.")
            Body("Como referencia: en reposo el ruido es de unos 0,2 µT; un reloj a 1–2 cm marca 40–75 µT.", muted = true)
            SignalMeter(live.signal, live.threshold)
            Text(verdict.first, style = MaterialTheme.typography.titleMedium, color = verdict.second)
        }
    }
    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        BigOutlineButton("Atrás", onBack, Modifier.weight(1f))
        BigButton("Listo", onNext, Modifier.weight(1f))
    }
}

@Composable
private fun Calibrate(app: MagneSenseApp, onBack: () -> Unit, onNext: () -> Unit) {
    val live by app.localGestures.live.collectAsState()
    var started by rememberSaveable { mutableStateOf(false) }
    val done = started && !live.calibrating
    Panel {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Title("Calibrar el reposo")
            Body("Aleja el imán, no toques el celular y toca Calibrar. Mide 2 segundos (el toque en la pantalla no cuenta).")
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                ConditionChip(
                    when {
                        !started -> "Sin calibrar"
                        live.calibrating -> "Calibrando…"
                        else -> "Calibrado"
                    },
                    done,
                )
                if (live.phoneMoving) ConditionChip("Celular moviéndose", false)
            }
            if (done) {
                val noisy = live.noise > NOISY_UT
                Text(
                    if (noisy) "! Ruido alto (%.2f µT): ¿hay metal cerca o se movió? Calibra de nuevo.".format(Locale.US, live.noise)
                    else "✓ Ruido en reposo %.2f µT.".format(Locale.US, live.noise),
                    style = MaterialTheme.typography.titleMedium,
                    color = if (noisy) Palette.WarningSoft else Palette.Ok,
                )
            }
        }
    }
    BigOutlineButton(if (started) "Calibrar de nuevo" else "Calibrar", {
        started = true
        app.localGestures.recalibrate()
    }, Modifier.fillMaxWidth(), enabled = !(started && live.calibrating))
    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        BigOutlineButton("Atrás", onBack, Modifier.weight(1f))
        BigButton("Siguiente", onNext, Modifier.weight(1f), enabled = done)
    }
}

@Composable
private fun QuackIntro(onTeach: () -> Unit, onSkip: () -> Unit) {
    Panel {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Title("Otro gesto para el cuack")
            Body("Usa un movimiento distinto al de la canción: acerca el imán por el otro lado del celular, o con el imán dado vuelta.")
            Body("Si los dos gestos se parecen, cada vez se dispara solo el más parecido.", muted = true)
        }
    }
    BigButton("Enseñar el cuack", onTeach, Modifier.fillMaxWidth())
    BigOutlineButton("Saltar", onSkip, Modifier.fillMaxWidth())
}

@Composable
private fun Done(app: MagneSenseApp, onDone: () -> Unit) {
    val state by app.localGestures.state.collectAsState()
    val names = state.phase2.detectors.map { it.name }
    Panel {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Title("¡Listo!")
            Body(
                if (names.isEmpty()) "No quedó ningún gesto aprendido. Puedes enseñarlos después en la pestaña Gestos."
                else "Gestos aprendidos: ${names.joinToString(", ")}. Haz el gesto de la canción para ponerla y otra vez para pararla.",
            )
            Body("Puedes volver a este asistente desde la pestaña Gestos.", muted = true)
        }
    }
    BigButton("Usar los gestos", {
        if (names.isNotEmpty()) app.settings.update { it.copy(activationMode = ActivationMode.GESTURES) }
        onDone()
    }, Modifier.fillMaxWidth())
}

@Composable
private fun Title(text: String) = Text(text, style = MaterialTheme.typography.titleLarge, color = Palette.Text)

@Composable
private fun Body(text: String, muted: Boolean = false) =
    Text(text, style = MaterialTheme.typography.bodyLarge, color = if (muted) Palette.Muted else Palette.Text)

private const val SONG_GESTURE = "cancion"
private const val QUACK_GESTURE = "pato"
private const val TICK_MS = 100L
private const val PEAK_DECAY = 0.97
/** Bajo esto el gesto apenas supera el umbral (piso de 1 µT). */
private const val WEAK_UT = 1.5
/** Desde aqui sobra margen sobre el ruido (σ ≈ 0,17 µT). */
private const val GOOD_UT = 5.0
private const val NOISY_UT = 1.0
