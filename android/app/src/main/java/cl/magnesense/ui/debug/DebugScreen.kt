package cl.magnesense.ui.debug

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import cl.magnesense.data.SettingsStore
import cl.magnesense.detector.Detector
import cl.magnesense.detector.Vec3
import cl.magnesense.sensor.SensorHub
import cl.magnesense.ui.components.Panel
import cl.magnesense.ui.components.ScreenColumn
import cl.magnesense.ui.components.SectionTitle
import cl.magnesense.ui.components.SignalMeter
import cl.magnesense.ui.components.ValueRow
import java.util.Locale

/** Valores en vivo para la demo y para ajustar parametros. */
@Composable
fun DebugScreen(detector: Detector, store: SettingsStore) {
    val s by SensorHub.snapshot.collectAsState()
    val d by detector.status.collectAsState()
    Column(Modifier.verticalScroll(rememberScrollState())) {
        ScreenColumn {
            Panel {
                Column {
                    SectionTitle("Detector")
                    ValueRow("Estado", d.state.name)
                    ValueRow("|ΔB|", "%.2f µT".format(Locale.US, d.signal))
                    ValueRow("Coseno", if (d.cosine.isNaN()) "-" else "%.3f".format(Locale.US, d.cosine))
                    ValueRow("Umbral on / off", "%.2f / %.2f µT".format(Locale.US, d.onThreshold, d.offThreshold))
                    ValueRow("Ruido σ", "%.3f µT".format(Locale.US, d.noise))
                    ValueRow("|ω|", "%.3f rad/s %s".format(Locale.US, d.gyroMagnitude, if (d.gyroOk) "(quieto)" else "(movimiento)"))
                    ValueRow("Muestreo", "%.0f Hz".format(Locale.US, d.sampleRateHz))
                    ValueRow("Saturado", if (d.saturated) "SÍ" else "no")
                    ValueRow("Activaciones", d.activations.toString())
                    d.magnet?.let {
                        ValueRow("Pico mediano", "%.1f µT".format(Locale.US, it.medianPeak))
                        ValueRow("Consistencia", "%.3f".format(Locale.US, it.consistency))
                    }
                    SignalMeter(d.signal, d.onThreshold)
                }
            }
            TuningPanel(d, store)
            Panel {
                Column {
                    SectionTitle("Últimos eventos")
                    val events = d.recentEvents.takeLast(8).reversed()
                    if (events.isEmpty()) ValueRow("-", "")
                    for (e in events) {
                        ValueRow(e.type.name, "%.1f µT".format(Locale.US, e.signal))
                    }
                }
            }
            Panel {
                Column {
                    SectionTitle("Magnetómetro")
                    ValueRow("Sensor", s.magSensorName.ifEmpty { "-" })
                    ValueRow("Tipo", if (s.magUncalibrated) "sin calibrar" else "calibrado")
                    ValueRow("Rango máx.", "%.0f µT".format(Locale.US, s.magMaxRange))
                    ValueRow("B (µT)", s.mag.fmt())
                    ValueRow("|B| terrestre", "%.1f µT".format(Locale.US, s.earthField))
                    ValueRow("Muestreo", "%.0f Hz".format(Locale.US, s.magRateHz))
                }
            }
            Panel {
                Column {
                    SectionTitle("Giroscopio")
                    ValueRow("Disponible", if (s.gyroAvailable) "sí" else "no")
                    ValueRow("ω (rad/s)", s.gyro.fmt())
                    ValueRow("Muestreo", "%.0f Hz".format(Locale.US, s.gyroRateHz))
                }
            }
            Panel {
                Column {
                    SectionTitle("Servicio")
                    ValueRow("Estado", if (s.running) "activo" else "detenido")
                }
            }
        }
    }
}

private fun Vec3.fmt(): String = "%7.2f %7.2f %7.2f".format(Locale.US, x, y, z)
