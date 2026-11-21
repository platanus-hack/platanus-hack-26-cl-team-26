package cl.magnesense.ui.pulses

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import cl.magnesense.MagneSenseApp
import cl.magnesense.data.ActivationMode
import cl.magnesense.pulses.PulseDecoder
import cl.magnesense.pulses.PulseInterp
import cl.magnesense.pulses.PulseProfile
import cl.magnesense.pulses.PulseUiState
import cl.magnesense.ui.components.BigButton
import cl.magnesense.ui.components.BigOutlineButton
import cl.magnesense.ui.components.ConditionChip
import cl.magnesense.ui.components.Panel
import cl.magnesense.ui.components.ScreenColumn
import cl.magnesense.ui.components.SignalMeter
import cl.magnesense.ui.gestures.Choice
import cl.magnesense.ui.gestures.ChoiceRow
import cl.magnesense.ui.theme.Palette
import java.util.Locale

/**
 * Modo Pulsos: secuencia en curso, barra punto/raya, tabla de comandos del perfil y texto Morse.
 * Un pulso corto es punto y uno largo es raya; tras un silencio la secuencia se ejecuta.
 */
@Composable
fun PulsesScreen(app: MagneSenseApp) {
    val s by app.pulses.state.collectAsState()
    val settings by app.settings.settings.collectAsState()
    val pulses = app.pulses

    Column(Modifier.verticalScroll(rememberScrollState())) {
        ScreenColumn {
            if (s.alarm) {
                Text(
                    "ALERTA AL CUIDADOR",
                    Modifier.fillMaxWidth().background(Palette.Warning, RoundedCornerShape(12.dp)).padding(12.dp),
                    color = Palette.OnHighlight,
                    style = MaterialTheme.typography.headlineSmall,
                    textAlign = TextAlign.Center,
                )
            }
            if (settings.activationMode != ActivationMode.PULSES) {
                Panel {
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text("Los pulsos no están activos: ahora manda \"${settings.activationMode.label}\".", color = Palette.WarningSoft, style = MaterialTheme.typography.bodyLarge)
                        BigButton("Usar pulsos", { app.settings.update { it.copy(activationMode = ActivationMode.PULSES) } }, Modifier.fillMaxWidth())
                    }
                }
            }

            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                ConditionChip(if (s.calibrating) "Calibrando…" else "Calibrado (σ %.2f µT)".format(Locale.US, s.noise), !s.calibrating)
                ConditionChip(if (s.phoneMoving) "Celular moviéndose" else "Celular quieto", !s.phoneMoving)
                if (s.lightOn) ConditionChip("Luz encendida", true)
            }

            Sequence(s)
            PulseBar(s)
            SignalMeter(s.signal, s.threshold)

            Panel {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Modo", style = MaterialTheme.typography.titleMedium, color = Palette.Text)
                    ChoiceRow(PulseInterp.entries.map { Choice(it.name, it.label) }, s.interp.name) { pulses.setInterp(PulseInterp.valueOf(it)) }
                    Text(s.interp.description, style = MaterialTheme.typography.bodyMedium, color = Palette.Muted)
                }
            }

            when (s.interp) {
                PulseInterp.COMMANDS -> Commands(s, onProfile = pulses::setProfile)
                PulseInterp.MORSE -> Morse(s, onSay = pulses::sayText, onClear = pulses::clearText)
                PulseInterp.DIRECT -> Panel {
                    Text(
                        "Cada vez que acercas el imán se prende o se apaga la linterna.",
                        style = MaterialTheme.typography.bodyLarge,
                        color = Palette.Text,
                    )
                }
            }

            Panel {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Tu ritmo", style = MaterialTheme.typography.titleMedium, color = Palette.Text)
                    Text(
                        if (s.learning) "Haz 3 pulsos cortos y después 3 largos: %d de %d.".format(s.learnCount, s.learnTotal)
                        else "Corto bajo %d ms, largo sobre eso. La secuencia se cierra tras %d ms de silencio.%s".format(
                            s.dotMaxMs, s.letterGapMs,
                            if (s.capUt > 0) " Golpes sobre %.0f µT no cuentan.".format(Locale.US, s.capUt) else "",
                        ),
                        style = MaterialTheme.typography.bodyMedium,
                        color = if (s.learning) Palette.Highlight else Palette.Muted,
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        BigOutlineButton("Aprender mi ritmo", pulses::learnTiming, Modifier.weight(1f), enabled = !s.learning && !s.calibrating)
                        BigOutlineButton("Recalibrar", pulses::recalibrate, Modifier.weight(1f))
                    }
                }
            }

            if (s.log.isNotEmpty()) {
                Panel {
                    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text("Últimos", style = MaterialTheme.typography.titleMedium, color = Palette.Text)
                        for (line in s.log) Text(line, style = MaterialTheme.typography.bodyMedium, color = Palette.Muted)
                    }
                }
            }
        }
    }
}

@Composable
private fun Sequence(s: PulseUiState) {
    Panel {
        Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(
                if (s.symbols.isEmpty()) "—" else PulseDecoder.pretty(s.symbols),
                fontSize = 56.sp,
                fontWeight = FontWeight.Bold,
                color = if (s.symbols.isEmpty()) Palette.Border else Palette.Highlight,
                fontFamily = FontFamily.Monospace,
            )
            s.last?.let {
                Text(
                    "${it.code}   ${it.text}",
                    style = MaterialTheme.typography.titleLarge,
                    color = if (it.ok) Palette.Ok else Palette.WarningSoft,
                    textAlign = TextAlign.Center,
                )
            }
        }
    }
}

/** Duracion del pulso en curso frente al limite punto/raya. */
@Composable
private fun PulseBar(s: PulseUiState) {
    val scale = (s.dotMaxMs * 2).coerceAtLeast(1)
    val frac = (s.pulseMs.toFloat() / scale).coerceIn(0f, 1f)
    val isDash = s.pulseMs >= s.dotMaxMs
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text("• punto", color = if (s.active && !isDash) Palette.Highlight else Palette.Muted, style = MaterialTheme.typography.bodyMedium)
            Text(if (s.active) "${s.pulseMs} ms" else "", color = Palette.Text, style = MaterialTheme.typography.bodyMedium, fontFamily = FontFamily.Monospace)
            Text("raya —", color = if (s.active && isDash) Palette.Highlight else Palette.Muted, style = MaterialTheme.typography.bodyMedium)
        }
        Box(
            Modifier.fillMaxWidth().height(28.dp)
                .background(Palette.Background, RoundedCornerShape(6.dp))
                .border(1.dp, Palette.Border, RoundedCornerShape(6.dp)),
        ) {
            Box(Modifier.fillMaxWidth(frac).height(28.dp).background(if (isDash) Palette.Warning else Palette.Highlight, RoundedCornerShape(6.dp)))
            Box(Modifier.fillMaxWidth(0.5f).height(28.dp), contentAlignment = Alignment.CenterEnd) {
                Box(Modifier.width(3.dp).height(28.dp).background(Palette.Text))
            }
        }
    }
}

@Composable
private fun Commands(s: PulseUiState, onProfile: (PulseProfile) -> Unit) {
    Panel {
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Perfil", style = MaterialTheme.typography.titleMedium, color = Palette.Text)
            ChoiceRow(PulseProfile.entries.map { Choice(it.name, it.label) }, s.profile.name) { onProfile(PulseProfile.valueOf(it)) }
            for (c in s.profile.commands) {
                val hit = s.last?.code == PulseDecoder.pretty(c.code)
                Row(
                    Modifier.fillMaxWidth().heightIn(min = 40.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        PulseDecoder.pretty(c.code),
                        Modifier.width(110.dp),
                        color = if (hit) Palette.Highlight else Palette.Text,
                        style = MaterialTheme.typography.titleLarge,
                        fontFamily = FontFamily.Monospace,
                    )
                    Text(c.text, color = if (hit) Palette.Highlight else Palette.Text, style = MaterialTheme.typography.bodyLarge)
                }
            }
        }
    }
}

@Composable
private fun Morse(s: PulseUiState, onSay: () -> Unit, onClear: () -> Unit) {
    Panel {
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Texto", style = MaterialTheme.typography.titleMedium, color = Palette.Text)
            Text(
                s.text.ifEmpty { "…" },
                style = MaterialTheme.typography.headlineMedium,
                color = Palette.Text,
                fontFamily = FontFamily.Monospace,
            )
            if (s.said.isNotEmpty()) Text("Dijo: ${s.said}", style = MaterialTheme.typography.bodyMedium, color = Palette.Muted)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                BigButton("Decir", onSay, Modifier.weight(1f), enabled = s.text.isNotBlank())
                BigOutlineButton("Borrar", onClear, Modifier.weight(1f), enabled = s.text.isNotEmpty())
            }
            Text(
                "A • —   E •   I • •   O — — —   S • • •   T —   …  (Ñ — — • — —)",
                style = MaterialTheme.typography.bodyMedium,
                color = Palette.Muted,
                fontFamily = FontFamily.Monospace,
            )
        }
    }
}
