package cl.magnesense.data

import android.content.Context
import cl.magnesense.actions.Device
import cl.magnesense.actions.DeviceKind
import cl.magnesense.detector.Calibration
import cl.magnesense.detector.MagnetCalibration
import cl.magnesense.detector.Vec3
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import org.json.JSONArray
import org.json.JSONObject

/**
 * Ajustes y calibracion guardados como JSON en SharedPreferences.
 * Lo leido se valida: si el formato cambio entre versiones se usan valores por defecto.
 */
class SettingsStore(context: Context) {

    private val prefs = context.getSharedPreferences("magnesense", Context.MODE_PRIVATE)

    private val _settings = MutableStateFlow(loadSettings())
    val settings: StateFlow<AppSettings> = _settings.asStateFlow()

    fun update(transform: (AppSettings) -> AppSettings) {
        _settings.update(transform)
        prefs.edit().putString(KEY_SETTINGS, encode(_settings.value).toString()).apply()
    }

    fun saveCalibration(c: Calibration) {
        prefs.edit().putString(KEY_CALIBRATION, encode(c).toString()).apply()
    }

    fun loadCalibration(): Calibration? =
        prefs.getString(KEY_CALIBRATION, null)?.let { runCatching { decodeCalibration(JSONObject(it)) }.getOrNull() }

    private fun loadSettings(): AppSettings =
        prefs.getString(KEY_SETTINGS, null)?.let { runCatching { decodeSettings(JSONObject(it)) }.getOrNull() }
            ?: AppSettings()

    private companion object {
        const val KEY_SETTINGS = "settings_v1"
        const val KEY_CALIBRATION = "calibration_v1"
        const val OLD_DEFAULT_MIN_COSINE = 0.85

        fun encode(s: AppSettings) = JSONObject()
            .put("devices", JSONArray(s.devices.map(::encode)))
            .put("scanStepMs", s.scanStepMs)
            .put("sensitivity", s.sensitivity)
            .put("holdMs", s.holdMs)
            .put("caregiverPhone", s.caregiverPhone)
            .put("caregiverWebhook", s.caregiverWebhook)
            .put("serverUrl", s.serverUrl)
            .put("startOnBoot", s.startOnBoot)
            .put("voiceEnabled", s.voiceEnabled)
            .put("phoneTorch", s.phoneTorch)
            .put("activationMode", s.activationMode.name)
            .put("gestureBindings", JSONObject(s.gestureBindings))
            .put("setupDone", s.setupDone)
            .put("pulsesIntroduced", true)
            .put(
                "tuning",
                JSONObject()
                    .put("peakMin", s.tuning.peakMin)
                    .put("peakMinSigma", s.tuning.peakMinSigma)
                    .put("kSigma", s.tuning.kSigma)
                    .put("peakFraction", s.tuning.peakFraction)
                    .put("minOn", s.tuning.minOn)
                    .put("minCosine", s.tuning.minCosine)
                    .put("directionCheck", s.tuning.directionCheck)
                    .put("acceptReversed", s.tuning.acceptReversed),
            )

        fun decodeTuning(o: JSONObject?): DetectionTuning {
            val d = DetectionTuning()
            if (o == null) return d
            fun num(key: String, def: Double, range: ClosedFloatingPointRange<Double>) =
                o.optDouble(key, def).takeIf { it.isFinite() }?.coerceIn(range) ?: def
            return DetectionTuning(
                peakMin = num("peakMin", d.peakMin, 0.2..20.0),
                peakMinSigma = num("peakMinSigma", d.peakMinSigma, 1.0..20.0),
                kSigma = num("kSigma", d.kSigma, 1.0..15.0),
                peakFraction = num("peakFraction", d.peakFraction, 0.1..0.9),
                minOn = num("minOn", d.minOn, 0.1..10.0),
                // 0,85 era el valor por defecto de v0.1.x y resulto demasiado estricto.
                minCosine = num("minCosine", d.minCosine, 0.0..0.99).let { if (it == OLD_DEFAULT_MIN_COSINE) d.minCosine else it },
                directionCheck = o.optBoolean("directionCheck", d.directionCheck),
                acceptReversed = o.optBoolean("acceptReversed", d.acceptReversed),
            )
        }

        fun decodeSettings(o: JSONObject): AppSettings {
            val d = AppSettings()
            val devices = o.optJSONArray("devices")?.let { arr ->
                (0 until arr.length()).mapNotNull { i -> arr.optJSONObject(i)?.let(::decodeDevice) }
            }
            return AppSettings(
                devices = devices?.takeIf { it.isNotEmpty() } ?: d.devices,
                scanStepMs = o.optLong("scanStepMs", d.scanStepMs).coerceIn(800, 6_000),
                sensitivity = o.optDouble("sensitivity", d.sensitivity).takeIf { it.isFinite() }?.coerceIn(0.5, 2.0) ?: d.sensitivity,
                holdMs = o.optLong("holdMs", d.holdMs).coerceIn(100, 1_500),
                caregiverPhone = o.optString("caregiverPhone", d.caregiverPhone),
                caregiverWebhook = o.optString("caregiverWebhook", d.caregiverWebhook),
                serverUrl = o.optString("serverUrl", d.serverUrl),
                startOnBoot = o.optBoolean("startOnBoot", d.startOnBoot),
                voiceEnabled = o.optBoolean("voiceEnabled", d.voiceEnabled),
                phoneTorch = o.optBoolean("phoneTorch", d.phoneTorch),
                tuning = decodeTuning(o.optJSONObject("tuning")),
                // v0.4: Pulsos pasa a ser el modo por defecto, tambien para quien ya tenia la app.
                activationMode = if (!o.has("pulsesIntroduced")) d.activationMode
                else runCatching { ActivationMode.valueOf(o.optString("activationMode")) }.getOrDefault(d.activationMode),
                gestureBindings = o.optJSONObject("gestureBindings")?.let { b ->
                    b.keys().asSequence().associateWith { b.optString(it) }.filterValues { it.isNotBlank() }
                } ?: d.gestureBindings,
                setupDone = o.optBoolean("setupDone", d.setupDone),
            )
        }

        fun encode(d: Device) = JSONObject()
            .put("id", d.id)
            .put("name", d.name)
            .put("icon", d.icon)
            .put("kind", d.kind.name)
            .put("onUrl", d.onUrl)
            .put("offUrl", d.offUrl)

        fun decodeDevice(o: JSONObject): Device? {
            val id = o.optString("id").ifBlank { return null }
            return Device(
                id = id,
                name = o.optString("name", id),
                icon = o.optString("icon", "🔌"),
                kind = runCatching { DeviceKind.valueOf(o.optString("kind")) }.getOrDefault(DeviceKind.SWITCH),
                onUrl = o.optString("onUrl"),
                offUrl = o.optString("offUrl"),
            )
        }

        fun encode(v: Vec3) = JSONArray(listOf(v.x, v.y, v.z))

        fun decodeVec(a: JSONArray) = Vec3(a.getDouble(0), a.getDouble(1), a.getDouble(2))

        fun encode(c: Calibration): JSONObject {
            val o = JSONObject().put("baseline", encode(c.baseline)).put("noise", c.noise)
            c.magnet?.let {
                o.put(
                    "magnet",
                    JSONObject()
                        .put("medianPeak", it.medianPeak)
                        .put("direction", encode(it.direction))
                        .put("consistency", it.consistency)
                        .put("minPeakCosine", it.minPeakCosine)
                        .put("peaks", JSONArray(it.peaks)),
                )
            }
            return o
        }

        fun decodeCalibration(o: JSONObject): Calibration {
            val magnet = o.optJSONObject("magnet")?.let { m ->
                val peaks = m.getJSONArray("peaks")
                MagnetCalibration(
                    medianPeak = m.getDouble("medianPeak"),
                    direction = decodeVec(m.getJSONArray("direction")),
                    consistency = m.getDouble("consistency"),
                    peaks = (0 until peaks.length()).map(peaks::getDouble),
                    minPeakCosine = m.optDouble("minPeakCosine", m.getDouble("consistency")),
                )
            }
            return Calibration(decodeVec(o.getJSONArray("baseline")), o.getDouble("noise"), magnet)
        }
    }
}
