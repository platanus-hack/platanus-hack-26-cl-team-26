package cl.magnesense.ui.gestures

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import cl.magnesense.MagneSenseApp
import cl.magnesense.actions.Device
import cl.magnesense.gestures.GestureMatcher
import cl.magnesense.remote.AgentReply
import cl.magnesense.remote.AgentStep
import cl.magnesense.remote.DetectorType
import cl.magnesense.remote.ServerApi
import cl.magnesense.remote.ServerJson
import cl.magnesense.ui.components.BigButton
import cl.magnesense.ui.components.BigOutlineButton
import cl.magnesense.ui.components.Field
import cl.magnesense.ui.components.Panel
import cl.magnesense.ui.components.SectionTitle
import cl.magnesense.ui.theme.Palette
import kotlinx.coroutines.launch

/**
 * Asistente en lenguaje natural ("cuando mueva el dedo a la izquierda, prende la luz").
 * Envia el pedido y el contexto a POST /agent del servidor (Claude) y muestra la respuesta
 * con pasos; cada paso se ejecuta solo cuando el cuidador toca "Hacer".
 */
@Composable
fun AssistantCard(app: MagneSenseApp, onTeach: (TeachDraft) -> Unit) {
    val server by app.localGestures.state.collectAsState()
    val devices by app.access.devices.collectAsState()
    val scope = rememberCoroutineScope()
    var text by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var reply by remember { mutableStateOf<AgentReply?>(null) }
    var notice by remember { mutableStateOf<String?>(null) }
    val done = remember { mutableStateListOf<Int>() }

    fun send() = scope.launch {
        busy = true
        notice = null
        reply = null
        done.clear()
        val body = ServerJson.agentBody(
            text = text.trim(),
            devices = devices.map { it.id to it.name },
            detectors = server.phase2.detectors,
            examples = server.examples,
            bindings = app.settings.settings.value.gestureBindings,
        )
        when (val r = app.serverApi.askAgent(body)) {
            is ServerApi.AgentOutcome.Reply -> {
                reply = r.reply
                if (r.reply.reply.isNotBlank()) app.speaker.speak(r.reply.reply)
            }
            ServerApi.AgentOutcome.NotAvailable -> notice = "El asistente todavía no está conectado en el servidor."
            is ServerApi.AgentOutcome.Error -> notice = r.message
        }
        busy = false
    }

    fun run(index: Int, step: AgentStep) {
        when (step) {
            is AgentStep.Record -> onTeach(TeachDraft(type = step.type, name = step.label))
            is AgentStep.Train -> scope.launch {
                busy = true
                val r = app.localGestures.train(step.request)
                busy = false
                if (r.ok) done += index else notice = r.error ?: "No se pudo crear el detector"
            }
            is AgentStep.Bind -> {
                app.settings.update { it.copy(gestureBindings = it.gestureBindings + (step.detector to step.target)) }
                done += index
            }
            is AgentStep.Unknown -> Unit
        }
    }

    Panel {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            SectionTitle("Asistente")
            Field("Pídele algo (p. ej. \"con el dedo a la izquierda, prende la luz\")", text) { text = it }
            BigButton(if (busy) "Pensando…" else "Enviar", { send() }, Modifier.fillMaxWidth(), enabled = !busy && text.isNotBlank())
            notice?.let { Text("! $it", style = MaterialTheme.typography.bodyLarge, color = Palette.WarningSoft) }
            reply?.let { r ->
                if (r.reply.isNotBlank()) Text(r.reply, style = MaterialTheme.typography.bodyLarge, color = Palette.Text)
                r.steps.forEachIndexed { i, step ->
                    StepRow(describe(step, devices), done = i in done, runnable = step !is AgentStep.Unknown && !busy) { run(i, step) }
                }
            }
        }
    }
}

@Composable
private fun StepRow(text: String, done: Boolean, runnable: Boolean, onRun: () -> Unit) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Text(
            (if (done) "✓ " else "• ") + text,
            style = MaterialTheme.typography.bodyLarge,
            color = if (done) Palette.Ok else Palette.Text,
            modifier = Modifier.weight(1f),
        )
        if (!done && runnable) BigOutlineButton("Hacer", onRun)
    }
}

private fun describe(step: AgentStep, devices: List<Device>): String = when (step) {
    is AgentStep.Record ->
        "Grabar ${step.count} ejemplos de \"${step.label}\" (${step.type.label.lowercase()})"
    is AgentStep.Train -> when (step.request.type) {
        DetectorType.EVENT ->
            "Crear el gesto \"${step.request.name}\" (se activa: ${GestureMatcher.triggerLabel(step.request.trigger.orEmpty())})"
        DetectorType.STATE -> "Crear la posición \"${step.request.name}\" (${step.request.labels.joinToString(" / ")})"
        DetectorType.RHYTHM -> "Crear el ritmo \"${step.request.name}\""
    }
    is AgentStep.Bind -> "Enlazar \"${step.detector}\" → ${targetLabel(step.target, devices)}"
    is AgentStep.Unknown -> "Paso \"${step.type}\" (esta versión de la app no lo sabe hacer)"
}
