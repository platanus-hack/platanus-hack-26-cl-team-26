package cl.magnesense.ui.gestures

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import cl.magnesense.MagneSenseApp
import cl.magnesense.data.AppSettings
import cl.magnesense.gestures.GestureMatcher
import cl.magnesense.remote.DetectorType
import cl.magnesense.remote.ServerApi
import cl.magnesense.remote.TrainRequest
import cl.magnesense.remote.TrainResult
import cl.magnesense.ui.components.BigButton
import cl.magnesense.ui.components.BigOutlineButton
import cl.magnesense.ui.components.Field
import cl.magnesense.ui.components.Panel
import cl.magnesense.ui.components.ScreenColumn
import cl.magnesense.ui.theme.Palette
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

private enum class Step { SETUP, RECORD, TRAIN, BIND }

/** Lo que se esta ensenando (tambien lo puede llenar el asistente). */
data class TeachDraft(
    val type: DetectorType = DetectorType.EVENT,
    val name: String = "",
    val stateLabels: List<String> = listOf("abierta", "cerrada"),
)

/**
 * Asistente para ensenar un gesto nuevo: nombre y tipo, grabar ejemplos, crear el detector
 * en el servidor y elegir que hace. El servidor solo detecta; la accion la hace la app.
 */
@Composable
fun TeachGestureFlow(app: MagneSenseApp, initial: TeachDraft = TeachDraft(), onClose: () -> Unit) {
    val server by app.server.state.collectAsState()
    val devices by app.access.devices.collectAsState()
    val scope = rememberCoroutineScope()

    var step by remember { mutableStateOf(Step.SETUP) }
    var type by remember { mutableStateOf(initial.type) }
    var name by remember { mutableStateOf(initial.name) }
    var labelA by remember { mutableStateOf(initial.stateLabels.getOrElse(0) { "abierta" }) }
    var labelB by remember { mutableStateOf(initial.stateLabels.getOrElse(1) { "cerrada" }) }
    var labelIndex by remember { mutableIntStateOf(0) }
    var countdown by remember { mutableIntStateOf(0) }
    var busy by remember { mutableStateOf(false) }
    var message by remember { mutableStateOf<String?>(null) }
    var trained by remember { mutableStateOf<TrainResult?>(null) }
    var trainedTrigger by remember { mutableStateOf<String?>(null) }
    var trigger by remember { mutableStateOf<String?>(null) }
    var target by remember { mutableStateOf<String?>(null) }

    val cleanName = name.trim().take(MAX_NAME)
    val labels = when (type) {
        DetectorType.EVENT -> listOf(cleanName)
        DetectorType.STATE -> listOf(labelA.trim(), labelB.trim())
        DetectorType.RHYTHM -> emptyList()
    }
    val currentLabel = labels.getOrNull(labelIndex).orEmpty()
    val recordingNow = server.recording.isNotEmpty()

    fun request(withTrigger: String?) = when (type) {
        DetectorType.EVENT -> TrainRequest(type, cleanName, label = cleanName, trigger = withTrigger ?: GestureMatcher.TRIGGER_ANY)
        DetectorType.STATE -> TrainRequest(type, cleanName, labels = labels, trigger = withTrigger ?: labels.first())
        DetectorType.RHYTHM -> TrainRequest(type, cleanName)
    }

    fun record() = scope.launch {
        busy = true
        message = null
        for (n in 3 downTo 1) {
            countdown = n
            app.speaker.speak(n.toString())
            delay(COUNTDOWN_STEP_MS)
        }
        countdown = 0
        app.speaker.speak("ahora")
        when (val r = app.serverApi.startRecording(currentLabel)) {
            is ServerApi.Outcome.Error -> {
                message = r.message
                busy = false
                return@launch
            }
            is ServerApi.Outcome.Ok -> Unit
        }
        if (type == DetectorType.EVENT) {
            delay(EVENT_RECORD_MS)
            val stop = app.serverApi.stopRecording()
            if (stop is ServerApi.Outcome.Error) message = stop.message
            busy = false
        }
        // Posiciones: se detiene con "Listo".
    }

    fun stopState() = scope.launch {
        val stop = app.serverApi.stopRecording()
        if (stop is ServerApi.Outcome.Error) message = stop.message
        busy = false
    }

    fun train(withTrigger: String?, then: () -> Unit) = scope.launch {
        busy = true
        message = null
        val r = app.serverApi.train(request(withTrigger))
        busy = false
        if (r.ok) {
            trained = r
            trainedTrigger = withTrigger ?: request(null).trigger
            then()
        } else {
            message = r.error ?: "No se pudo crear el detector"
        }
    }

    fun save() {
        val chosenTrigger = trigger ?: trainedTrigger
        val finish = {
            val bound = target ?: AppSettings.BIND_NONE
            app.settings.update { it.copy(gestureBindings = it.gestureBindings + (cleanName to bound)) }
            onClose()
        }
        // Cambiar la regla = volver a crear el detector con los mismos ejemplos (reemplaza al anterior).
        if (type != DetectorType.RHYTHM && chosenTrigger != trainedTrigger) train(chosenTrigger) { finish() } else finish()
    }

    Column(Modifier.verticalScroll(rememberScrollState())) {
        ScreenColumn {
            Text("Enseñar un gesto", style = MaterialTheme.typography.headlineMedium, color = Palette.Text)
            message?.let { Text("! $it", style = MaterialTheme.typography.titleMedium, color = Palette.WarningSoft) }
            if (!server.connected) {
                Text(
                    "! Sin conexión con el servidor: no se pueden grabar ejemplos.",
                    style = MaterialTheme.typography.titleMedium,
                    color = Palette.WarningSoft,
                )
            }

            when (step) {
                Step.SETUP -> {
                    Panel {
                        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                            Field("Nombre del gesto (p. ej. izquierda)", name) { name = it }
                            Text("¿Qué tipo de gesto es?", style = MaterialTheme.typography.titleMedium, color = Palette.Text)
                            for (t in DetectorType.entries) TypeOption(t, t == type) { type = t }
                            if (type == DetectorType.STATE) {
                                Field("Posición 1 (la que activa)", labelA) { labelA = it }
                                Field("Posición 2", labelB) { labelB = it }
                            }
                            if (app.server.state.value.phase2.detectors.any { it.name == cleanName }) {
                                Text(
                                    "Ya existe un gesto con ese nombre: se reemplazará.",
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = Palette.WarningSoft,
                                )
                            }
                        }
                    }
                    val valid = cleanName.isNotEmpty() &&
                        (type != DetectorType.STATE || (labels.all { it.isNotEmpty() } && labels.distinct().size == 2))
                    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        BigOutlineButton("Cancelar", onClose, Modifier.weight(1f))
                        BigButton("Siguiente", {
                            labelIndex = 0
                            step = if (type == DetectorType.RHYTHM) Step.TRAIN else Step.RECORD
                        }, Modifier.weight(1f), enabled = valid)
                    }
                }

                Step.RECORD -> {
                    val count = server.examples[currentLabel] ?: 0
                    Panel {
                        Column(verticalArrangement = Arrangement.spacedBy(12.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                            Text(
                                if (type == DetectorType.STATE) "Pon la mano en \"$currentLabel\" y quédate así" else "Haz el gesto \"$currentLabel\"",
                                style = MaterialTheme.typography.titleLarge,
                                color = Palette.Text,
                                textAlign = TextAlign.Center,
                            )
                            Text(
                                if (type == DetectorType.STATE) "Toca Grabar, mantén la posición y toca Listo."
                                else "Toca Grabar: después de \"3, 2, 1, ahora\" haz el gesto una vez (hay 2 segundos).",
                                style = MaterialTheme.typography.bodyMedium,
                                color = Palette.Muted,
                                textAlign = TextAlign.Center,
                            )
                            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                                repeat(RECOMMENDED_EXAMPLES) { i -> Dot(i < count) }
                            }
                            Text("$count ejemplos (mínimo $MIN_EXAMPLES)", style = MaterialTheme.typography.bodyLarge, color = Palette.Text)
                            when {
                                countdown > 0 -> Text("$countdown", fontSize = 72.sp, color = Palette.Highlight)
                                recordingNow -> Text("● Grabando…", style = MaterialTheme.typography.headlineMedium, color = Palette.Highlight)
                            }
                            if (type == DetectorType.STATE && recordingNow) {
                                BigButton("Listo", { stopState() }, Modifier.fillMaxWidth())
                            } else {
                                BigButton("Grabar", { record() }, Modifier.fillMaxWidth(), enabled = !busy && server.connected)
                            }
                            BigOutlineButton("Borrar ejemplos de \"$currentLabel\"", {
                                scope.launch { app.serverApi.clearExamples(currentLabel) }
                            }, Modifier.fillMaxWidth(), enabled = !busy && count > 0)
                        }
                    }
                    val enough = count >= MIN_EXAMPLES
                    val last = labelIndex == labels.lastIndex
                    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        BigOutlineButton("Atrás", { if (labelIndex > 0) labelIndex-- else step = Step.SETUP }, Modifier.weight(1f), enabled = !busy)
                        BigButton(if (last) "Siguiente" else "Siguiente posición", {
                            if (last) step = Step.TRAIN else labelIndex++
                        }, Modifier.weight(1f), enabled = enough && !busy)
                    }
                }

                Step.TRAIN -> {
                    Panel {
                        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                            Text("Crear el detector \"$cleanName\"", style = MaterialTheme.typography.titleLarge, color = Palette.Text)
                            Text(
                                if (type == DetectorType.RHYTHM) "No necesita ejemplos: aprende el ritmo mientras ocurre."
                                else "El servidor aprende de los ejemplos grabados.",
                                style = MaterialTheme.typography.bodyMedium,
                                color = Palette.Muted,
                            )
                            trained?.let { QualityText(it) }
                        }
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        BigOutlineButton("Atrás", { step = if (type == DetectorType.RHYTHM) Step.SETUP else Step.RECORD }, Modifier.weight(1f), enabled = !busy)
                        if (trained == null) {
                            BigButton(if (busy) "Creando…" else "Crear detector", { train(null) {} }, Modifier.weight(1f), enabled = !busy && server.connected)
                        } else {
                            BigButton("Siguiente", {
                                trigger = trainedTrigger
                                step = Step.BIND
                            }, Modifier.weight(1f))
                        }
                    }
                }

                Step.BIND -> {
                    Panel {
                        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                            when (type) {
                                DetectorType.EVENT -> {
                                    Text("¿Cuándo se activa?", style = MaterialTheme.typography.titleMedium, color = Palette.Text)
                                    ChoiceRow(GestureMatcher.EVENT_TRIGGERS.map { Choice(it, GestureMatcher.triggerLabel(it)) }, trigger) { trigger = it }
                                }
                                DetectorType.STATE -> {
                                    Text("¿Qué posición activa la acción?", style = MaterialTheme.typography.titleMedium, color = Palette.Text)
                                    ChoiceRow(labels.map { Choice(it, it) }, trigger) { trigger = it }
                                }
                                DetectorType.RHYTHM -> Text(
                                    "Se activa cuando el movimiento se detiene.",
                                    style = MaterialTheme.typography.bodyLarge,
                                    color = Palette.Text,
                                )
                            }
                            Text("¿Qué hace este gesto?", style = MaterialTheme.typography.titleMedium, color = Palette.Text)
                            TargetPicker(devices, target) { target = it }
                        }
                    }
                    BigButton(if (busy) "Guardando…" else "Guardar", { save() }, Modifier.fillMaxWidth(), enabled = !busy && target != null)
                }
            }
        }
    }
}

@Composable
private fun TypeOption(type: DetectorType, selected: Boolean, onClick: () -> Unit) {
    val shape = RoundedCornerShape(14.dp)
    Column(
        Modifier
            .fillMaxWidth()
            .background(if (selected) Palette.Highlight else Palette.Background, shape)
            .border(1.dp, Palette.Border, shape)
            .clickable(onClick = onClick)
            .padding(14.dp),
    ) {
        Text(
            (if (selected) "● " else "○ ") + type.label,
            style = MaterialTheme.typography.titleMedium,
            color = if (selected) Palette.OnHighlight else Palette.Text,
        )
        Text(type.description, style = MaterialTheme.typography.bodyMedium, color = if (selected) Palette.OnHighlight else Palette.Muted)
    }
}

@Composable
private fun QualityText(r: TrainResult) {
    val text = when {
        r.consistency != null -> if (r.good) {
            "✓ Gesto claro: los ejemplos se parecen entre sí (%.2f)".format(r.consistency)
        } else {
            "! Los ejemplos se parecen poco (%.2f): graba más, siempre con el mismo movimiento".format(r.consistency)
        }
        r.separation != null -> if (r.good) {
            "✓ Las posiciones se distinguen bien (%.1f)".format(r.separation)
        } else {
            "! Las posiciones se parecen (%.1f): sepáralas más o graba más ejemplos".format(r.separation)
        }
        else -> "✓ Detector creado"
    }
    Text(text, style = MaterialTheme.typography.titleMedium, color = if (r.good) Palette.Ok else Palette.WarningSoft)
}

@Composable
private fun Dot(filled: Boolean) {
    Box(
        Modifier
            .size(34.dp)
            .background(if (filled) Palette.Highlight else Palette.Background, CircleShape)
            .border(3.dp, if (filled) Palette.Highlight else Palette.Border, CircleShape),
    )
}

private const val MAX_NAME = 40
private const val MIN_EXAMPLES = 3
private const val RECOMMENDED_EXAMPLES = 5
private const val COUNTDOWN_STEP_MS = 800L
private const val EVENT_RECORD_MS = 2_000L
