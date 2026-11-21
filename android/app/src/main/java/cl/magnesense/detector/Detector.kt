package cl.magnesense.detector

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

/**
 * Detector de "pulsaciones" de un iman pasivo a partir del magnetometro.
 *
 * Basado en el Detector de server.py (umbral sobre |B - base| con suavizado, duracion minima,
 * histeresis y seguimiento de deriva) y extendido con calibracion de reposo y del iman,
 * chequeo de direccion, pausa por giroscopio, periodo refractario y aviso de saturacion.
 *
 * Kotlin puro: no depende de Android, asi se prueba con datos sinteticos.
 * Las llamadas publicas estan sincronizadas (sensores en un hilo, comandos desde la UI).
 */
class Detector(config: DetectorConfig = DetectorConfig()) {

    @Volatile
    var config: DetectorConfig = config
        set(value) {
            field = value
            publish()
        }

    private val _status = MutableStateFlow(DetectorStatus())
    val status: StateFlow<DetectorStatus> = _status.asStateFlow()

    val state: DetectorState get() = currentState

    // --- Estado general ---
    private var currentState = DetectorState.UNCALIBRATED
    private var smooth: Vec3? = null
    private var lastMagT = Double.NaN
    private var baseline: Vec3? = null
    private var noise = 0.0
    private var magnet: MagnetCalibration? = null
    private var signal = 0.0
    private var cosine = Double.NaN
    private var progress = 0.0
    private var activations = 0
    private val rate = RateMeter()
    private val recent = ArrayDeque<DetectorEvent>()

    // --- Sensor ---
    private var sensorMaxRange = 0.0
    private var gyroAvailable = false
    private var gyroMagnitude = 0.0
    private var lastMotionT = Double.NEGATIVE_INFINITY

    // --- Calibracion en reposo ---
    private var calibStart = Double.NaN
    private val calibSamples = ArrayList<Vec3>()
    private var lastRestartEventT = Double.NEGATIVE_INFINITY

    // --- Calibracion del iman ---
    private val peaks = ArrayList<Pair<Double, Vec3>>()
    private var inPeak = false
    private var peakMax = 0.0
    private var peakDir = Vec3.ZERO

    // --- Deteccion ---
    private var candidateSince = Double.NaN
    private var wrongSince = Double.NaN
    private var lastIgnoredT = Double.NEGATIVE_INFINITY
    private var lastActivationT = Double.NEGATIVE_INFINITY
    private var activeSince = Double.NaN

    // --- Re-medicion de la base tras una pausa ---
    private var rebaseStart = Double.NaN
    private var rebaseSum = Vec3.ZERO
    private var rebaseCount = 0
    private var announceResume = true

    // --- Saturacion ---
    private var satSince = Double.NaN
    private var saturated = false
    private var lastSatWarnT = Double.NEGATIVE_INFINITY

    // ------------------------------------------------------------------
    // Umbrales
    // ------------------------------------------------------------------

    val onThreshold: Double
        get() {
            val c = config
            val fromPeak = magnet?.let { c.peakFraction * it.medianPeak } ?: 0.0
            val base = max(c.kSigma * noise, fromPeak) / c.sensitivity.coerceAtLeast(0.05)
            return max(base, c.minOnThreshold)
        }

    val offThreshold: Double get() = onThreshold * config.offRatio

    /** Lo que debe superar cada acercamiento durante la calibracion del iman. */
    val magnetPeakThreshold: Double
        get() = max(config.magnetPeakMinSigma * noise, config.magnetPeakMin)

    /**
     * Coseno minimo que se exige de verdad: el configurado, pero nunca mas estricto que el peor
     * acercamiento de la calibracion (menos un margen). Asi se adapta a como se mueve cada persona.
     */
    val effectiveMinCosine: Double
        get() {
            val c = config
            val m = magnet ?: return c.minCosine
            return min(c.minCosine, m.minPeakCosine - c.cosineMargin).coerceAtLeast(-1.0)
        }

    /** Si [cosine] (de una lectura fuerte) cuenta como "la direccion del iman". */
    private fun directionMatches(): Boolean {
        val c = config
        if (magnet == null || !c.directionCheck) return true
        if (cosine.isNaN()) return false
        val cos = if (c.acceptReversed) kotlin.math.abs(cosine) else cosine
        return cos >= effectiveMinCosine
    }

    // ------------------------------------------------------------------
    // Comandos
    // ------------------------------------------------------------------

    @Synchronized
    fun setSensorInfo(maxRange: Double, hasGyroscope: Boolean) {
        sensorMaxRange = maxRange
        gyroAvailable = hasGyroscope
        publish()
    }

    /** Paso 1: dejar el celular y el iman quietos [DetectorConfig.restCalibrationSeconds]. */
    @Synchronized
    fun startRestCalibration() {
        currentState = DetectorState.CALIBRATING_REST
        calibStart = Double.NaN
        calibSamples.clear()
        progress = 0.0
        resetDetection()
        publish()
    }

    /** Paso 2: acercar el iman [DetectorConfig.magnetPeaksRequired] veces. Requiere el paso 1. */
    @Synchronized
    fun startMagnetCalibration(): Boolean {
        if (baseline == null) return false
        currentState = DetectorState.CALIBRATING_MAGNET
        peaks.clear()
        inPeak = false
        resetDetection()
        publish()
        return true
    }

    /** Vuelve a detectar con la calibracion que haya (o queda sin calibrar). */
    @Synchronized
    fun cancelCalibration() {
        currentState = if (baseline != null) DetectorState.REST else DetectorState.UNCALIBRATED
        calibSamples.clear()
        peaks.clear()
        inPeak = false
        progress = 0.0
        resetDetection()
        publish()
    }

    /** Restaura una calibracion guardada; la base se vuelve a medir con el celular quieto. */
    @Synchronized
    fun restore(calibration: Calibration) {
        baseline = calibration.baseline
        noise = max(calibration.noise, config.noiseFloor)
        magnet = calibration.magnet
        beginPause(announce = false)
        lastMotionT = Double.NEGATIVE_INFINITY
        publish()
    }

    @Synchronized
    fun calibration(): Calibration? = baseline?.let { Calibration(it, noise, magnet) }

    /**
     * Toma la lectura actual suavizada como nueva linea base (0 µT) al instante,
     * conservando el ruido y el iman calibrados. Ideal para re-centrar en 1 toque.
     */
    @Synchronized
    fun recenterBaseline() {
        val current = smooth ?: return
        baseline = current
        if (noise <= 0.0) noise = config.noiseFloor
        signal = 0.0
        cosine = Double.NaN
        if (currentState == DetectorState.UNCALIBRATED || currentState == DetectorState.PAUSED ||
            currentState == DetectorState.CANDIDATE || currentState == DetectorState.ACTIVE ||
            currentState == DetectorState.REFRACTORY
        ) {
            currentState = DetectorState.REST
        }
        resetDetection()
        publish()
    }

    // ------------------------------------------------------------------
    // Muestras
    // ------------------------------------------------------------------

    /** Procesa una lectura del magnetometro ([t] en segundos, [b] en µT). */
    @Synchronized
    fun processMagnetometer(t: Double, b: Vec3): List<DetectorEvent> {
        val events = ArrayList<DetectorEvent>(2)
        rate.tick(t)
        val dt = if (lastMagT.isNaN()) 0.0 else (t - lastMagT).coerceIn(0.0, 0.5)
        lastMagT = t
        val s = smooth?.approach(b, if (dt > 0) dt / (config.smoothTau + dt) else 1.0) ?: b
        smooth = s

        checkSaturation(t, b, events)

        when (currentState) {
            DetectorState.UNCALIBRATED -> signal = 0.0
            DetectorState.CALIBRATING_REST -> restCalibrationStep(t, s, events)
            DetectorState.PAUSED -> {
                measure(s)
                pausedStep(t, s, events)
            }
            DetectorState.CALIBRATING_MAGNET -> {
                val delta = measure(s)
                magnetCalibrationStep(t, delta, events)
            }
            else -> {
                measure(s)
                val raw = (b - baseline!!).norm
                detectionStep(t, s, raw, dt, events)
            }
        }
        record(events)
        publish()
        return events
    }

    /** Procesa una lectura del giroscopio ([w] en rad/s). */
    @Synchronized
    fun processGyroscope(t: Double, w: Vec3): List<DetectorEvent> {
        val events = ArrayList<DetectorEvent>(1)
        gyroAvailable = true
        gyroMagnitude = w.norm
        val moving = gyroMagnitude > config.gyroLimit
        // Ignorar la vibracion haptica propia del telefono justo al activar (0.6 s).
        val selfVibration = (t - lastActivationT in 0.0..0.6) && gyroMagnitude < config.gyroLimit * 3.0
        if (moving && !selfVibration) lastMotionT = t
        if (moving && !selfVibration) {
            when (currentState) {
                DetectorState.CALIBRATING_REST -> {
                    calibStart = Double.NaN
                    calibSamples.clear()
                    progress = 0.0
                    if (t - lastRestartEventT >= 1.0) {
                        lastRestartEventT = t
                        events += DetectorEvent(EventType.CALIBRATION_RESTARTED, t)
                    }
                }
                DetectorState.REST, DetectorState.CANDIDATE,
                DetectorState.ACTIVE, DetectorState.REFRACTORY -> {
                    beginPause(announce = true)
                    events += DetectorEvent(EventType.PAUSED, t)
                }
                DetectorState.PAUSED -> rebaseStart = Double.NaN
                else -> Unit
            }
        }
        if (events.isNotEmpty()) record(events)
        return events
    }

    // ------------------------------------------------------------------
    // Pasos internos
    // ------------------------------------------------------------------

    /** Actualiza senal y coseno contra la base; devuelve B - base. */
    private fun measure(s: Vec3): Vec3 {
        val delta = s - baseline!!
        signal = delta.norm
        val dir = magnet?.direction
        cosine = if (dir == null || signal < 1e-9) Double.NaN else (delta dot dir) / signal
        return delta
    }

    private fun restCalibrationStep(t: Double, s: Vec3, events: MutableList<DetectorEvent>) {
        signal = 0.0
        if (calibStart.isNaN()) calibStart = t
        val c = config
        // El primer instante incluye el toque en "Empezar": no se usa.
        if (t - calibStart >= c.restSettleSeconds) calibSamples += s
        progress = ((t - calibStart) / c.restCalibrationSeconds).coerceIn(0.0, 1.0)
        if (t - calibStart >= c.restCalibrationSeconds && calibSamples.size >= 10) {
            baseline = medianVector(calibSamples)
            noise = max(robustNoise(calibSamples, rate.rateHz), c.noiseFloor)
            calibSamples.clear()
            progress = 1.0
            currentState = DetectorState.REST
            resetDetection()
            events += DetectorEvent(EventType.REST_CALIBRATED, t, signal = noise)
        }
    }

    /** Mediana por eje: un golpe breve durante la calibracion no mueve la base. */
    private fun medianVector(v: List<Vec3>): Vec3 =
        Vec3(median(v.map { it.x }), median(v.map { it.y }), median(v.map { it.z }))

    /**
     * Ruido σ robusto: mediana de |B - promedio movil de ~1 s|, escalada para que con ruido
     * gaussiano coincida con el RMS (para |N(0,σ²I₃)| el RMS es ≈ 1,13 × la mediana).
     * Asi ni la deriva lenta ni un golpe aislado inflan el umbral.
     */
    private fun robustNoise(v: List<Vec3>, rateHz: Double): Double {
        val n = v.size
        val w = (if (rateHz > 0) rateHz else DEFAULT_RATE_HZ).toInt().coerceIn(5, n / 2).let { it - it % 2 }
        if (n < 2 * w) {
            val m = medianVector(v)
            return sqrt(v.sumOf { val d = (it - m).norm; d * d } / n)
        }
        val prefix = ArrayList<Vec3>(n + 1).apply { add(Vec3.ZERO) }
        for (s in v) prefix += prefix.last() + s
        val half = w / 2
        val deviations = DoubleArray(n - w) { k ->
            val i = k + half
            val mean = (prefix[i + half] - prefix[i - half]) / w.toDouble()
            (v[i] - mean).norm
        }
        return RMS_PER_MEDIAN_3D * median(deviations.toList())
    }

    private fun median(values: List<Double>): Double {
        val s = values.sorted()
        val n = s.size
        return if (n % 2 == 1) s[n / 2] else (s[n / 2 - 1] + s[n / 2]) / 2
    }

    private fun magnetCalibrationStep(t: Double, delta: Vec3, events: MutableList<DetectorEvent>) {
        val c = config
        val start = magnetPeakThreshold
        if (!inPeak) {
            if (signal > start) {
                inPeak = true
                peakMax = signal
                peakDir = delta.normalized()
            }
            return
        }
        if (signal > peakMax) {
            peakMax = signal
            peakDir = delta.normalized()
        }
        if (signal < max(start / 2, peakMax * 0.35)) {
            inPeak = false
            peaks += peakMax to peakDir
            events += DetectorEvent(EventType.MAGNET_PEAK, t, signal = peakMax)
            if (peaks.size >= c.magnetPeaksRequired) finishMagnetCalibration(t, events)
        }
    }

    private fun finishMagnetCalibration(t: Double, events: MutableList<DetectorEvent>) {
        val n = peaks.size
        val median = median(peaks.map { it.first })
        var sum = Vec3.ZERO
        for ((_, d) in peaks) sum += d
        val mean = sum.normalized()
        val consistency = peaks.sumOf { it.second dot mean } / n
        val worst = peaks.minOf { it.second dot mean }
        magnet = MagnetCalibration(median, mean, consistency, peaks.map { it.first }, minPeakCosine = worst)
        peaks.clear()
        currentState = DetectorState.REST
        resetDetection()
        events += DetectorEvent(EventType.MAGNET_CALIBRATED, t, signal = median, cosine = consistency)
    }

    private fun detectionStep(t: Double, s: Vec3, raw: Double, dt: Double, events: MutableList<DetectorEvent>) {
        val c = config
        val on = onThreshold
        val off = offThreshold
        val dirOk = directionMatches()
        when (currentState) {
            DetectorState.REST -> {
                if (signal > on && raw > off) {
                    if (dirOk) {
                        currentState = DetectorState.CANDIDATE
                        candidateSince = t
                        wrongSince = Double.NaN
                    } else {
                        wrongDirection(t, s, events)
                    }
                } else {
                    wrongSince = Double.NaN
                    // Deriva lenta: solo con la senal claramente en reposo y el celular quieto.
                    if (signal < off && dt > 0 && t - lastMotionT >= c.stillSecondsToResume) {
                        baseline = baseline!!.approach(s, min(dt / c.driftTau, 1.0))
                    }
                }
            }
            DetectorState.CANDIDATE -> when {
                signal <= on || raw <= off -> currentState = DetectorState.REST
                !dirOk -> {
                    currentState = DetectorState.REST
                    wrongDirection(t, s, events)
                }
                t - candidateSince >= c.holdSeconds -> {
                    currentState = DetectorState.ACTIVE
                    lastActivationT = t
                    activeSince = t
                    activations++
                    events += DetectorEvent(EventType.ACTIVATED, t, signal, cosine)
                }
            }
            DetectorState.ACTIVE -> when {
                signal < off -> currentState =
                    if (t - lastActivationT >= c.refractorySeconds) DetectorState.REST else DetectorState.REFRACTORY
                t - activeSince >= c.stuckSeconds -> rebaseline(t, s, events)
            }
            DetectorState.REFRACTORY -> when {
                // Debe bajar de "off" otra vez antes de poder activar.
                signal >= off -> {
                    currentState = DetectorState.ACTIVE
                    activeSince = t
                }
                t - lastActivationT >= c.refractorySeconds -> currentState = DetectorState.REST
            }
            else -> Unit
        }
    }

    private fun wrongDirection(t: Double, s: Vec3, events: MutableList<DetectorEvent>) {
        val c = config
        if (wrongSince.isNaN()) {
            wrongSince = t
            return
        }
        val held = t - wrongSince
        if (held >= c.stuckSeconds) {
            // Un objeto quedo cerca: aceptarlo como nueva base.
            rebaseline(t, s, events)
        } else if (held >= c.holdSeconds && t - lastIgnoredT >= c.ignoredMinInterval) {
            lastIgnoredT = t
            events += DetectorEvent(EventType.IGNORED, t, signal, cosine)
        }
    }

    private fun rebaseline(t: Double, s: Vec3, events: MutableList<DetectorEvent>) {
        baseline = s
        currentState = DetectorState.REST
        resetDetection()
        signal = 0.0
        events += DetectorEvent(EventType.REBASELINED, t)
    }

    private fun beginPause(announce: Boolean) {
        currentState = DetectorState.PAUSED
        announceResume = announce
        rebaseStart = Double.NaN
        progress = 0.0
        resetDetection()
    }

    private fun pausedStep(t: Double, s: Vec3, events: MutableList<DetectorEvent>) {
        val c = config
        val still = t - lastMotionT
        if (still < c.stillSecondsToResume) {
            progress = (still / (c.stillSecondsToResume + c.rebaselineSeconds)).coerceIn(0.0, 1.0)
            return
        }
        if (rebaseStart.isNaN()) {
            rebaseStart = t
            rebaseSum = Vec3.ZERO
            rebaseCount = 0
        }
        rebaseSum += s
        rebaseCount++
        val elapsed = t - rebaseStart
        progress = ((c.stillSecondsToResume + elapsed) / (c.stillSecondsToResume + c.rebaselineSeconds)).coerceIn(0.0, 1.0)
        if (elapsed >= c.rebaselineSeconds && rebaseCount >= 5) {
            baseline = rebaseSum / rebaseCount.toDouble()
            currentState = DetectorState.REST
            resetDetection()
            progress = 1.0
            signal = 0.0
            events += DetectorEvent(if (announceResume) EventType.RESUMED else EventType.REBASELINED, t)
        }
    }

    private fun checkSaturation(t: Double, b: Vec3, events: MutableList<DetectorEvent>) {
        val c = config
        if (sensorMaxRange <= 0 || b.maxAbs() < c.saturationFraction * sensorMaxRange) {
            satSince = Double.NaN
            saturated = false
            return
        }
        if (satSince.isNaN()) satSince = t
        if (t - satSince >= c.saturationSeconds) {
            saturated = true
            if (t - lastSatWarnT >= c.saturationWarnInterval) {
                lastSatWarnT = t
                events += DetectorEvent(EventType.SATURATED, t, b.maxAbs())
            }
        }
    }

    private fun resetDetection() {
        candidateSince = Double.NaN
        wrongSince = Double.NaN
        activeSince = Double.NaN
    }

    private fun record(events: List<DetectorEvent>) {
        if (events.isEmpty()) return
        for (e in events) {
            recent.addLast(e)
            while (recent.size > config.maxRecentEvents) recent.removeFirst()
        }
    }

    private fun publish() {
        _status.value = DetectorStatus(
            state = currentState,
            signal = signal,
            cosine = cosine,
            minCosine = effectiveMinCosine,
            directionCheck = config.directionCheck && magnet != null,
            onThreshold = onThreshold,
            offThreshold = offThreshold,
            peakThreshold = magnetPeakThreshold,
            noise = noise,
            baseline = baseline,
            gyroAvailable = gyroAvailable,
            gyroMagnitude = gyroMagnitude,
            gyroOk = gyroMagnitude <= config.gyroLimit,
            saturated = saturated,
            sampleRateHz = rate.rateHz,
            progress = progress,
            magnetPeaks = if (currentState == DetectorState.CALIBRATING_MAGNET) peaks.map { it.first } else emptyList(),
            magnet = magnet,
            activations = activations,
            recentEvents = recent.toList(),
        )
    }

    private companion object {
        const val DEFAULT_RATE_HZ = 100.0

        /** RMS / mediana de |v| para ruido gaussiano isotropo en 3 ejes (distribucion chi, 3 g.l.). */
        const val RMS_PER_MEDIAN_3D = 1.13
    }
}
