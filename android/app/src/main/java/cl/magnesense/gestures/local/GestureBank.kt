package cl.magnesense.gestures.local

import cl.magnesense.detector.Vec3

/** Un gesto aprendido y cuando dispara: any (al empezar) | short | long | double. */
class BoundGesture(val detector: EventGestureDetector, val label: String, val trigger: String)

/** Lo que hace falta para volver a armar un gesto (se guarda en disco). */
data class GestureSpec(val name: String, val label: String, val trigger: String, val minOnMs: Int)

/** Resultado de entrenar, con la calidad en numeros y un aviso si la senal es debil. */
data class TrainOutcome(
    val ok: Boolean,
    val name: String = "",
    val consistency: Double? = null,
    val threshold: Double? = null,
    val peak: Double? = null,
    val warning: String? = null,
    val error: String? = null,
)

/**
 * Banco de gestos aprendidos, en Kotlin puro (port de Bank + la grabacion de server.py).
 * Todo corre en el celular: calibrar, grabar ejemplos, entrenar y detectar.
 *
 * No es seguro entre hilos: quien lo usa debe sincronizar.
 */
class GestureBank(val pipeline: GesturePipeline = GesturePipeline()) {

    private val gestures = LinkedHashMap<String, BoundGesture>()
    private val specs = LinkedHashMap<String, GestureSpec>()

    /** Ejemplos por etiqueta: el cambio (B − reposo) de cada grabacion. */
    val examples = LinkedHashMap<String, MutableList<List<Vec3>>>()

    /** Etiqueta que se esta grabando, o "". */
    var recording = ""
        private set
    private var recBase: Vec3? = null
    private val recDelta = ArrayList<Vec3>()

    private var muteUntil = Double.NEGATIVE_INFINITY
    private var pendingMute = 0.0
    private var wasCalibrating = true

    /** Ultimo |B − reposo| (µT), para mostrar en vivo. */
    var lastSignal = 0.0
        private set

    val detectors: Collection<BoundGesture> get() = gestures.values
    val savedSpecs: Collection<GestureSpec> get() = specs.values

    fun gyro(t: Double, w: Vec3) = pipeline.gyro(t, w)

    fun recalibrate() {
        pipeline.recalibrate()
        wasCalibrating = true
    }

    /** Procesa una lectura del magnetometro. Cada evento va con true si no debe actuar (calibrando o grabando). */
    fun step(t: Double, v: Vec3): List<Pair<GestureEvent, Boolean>> {
        val p = pipeline
        var delta = p.step(t, v)
        if (pendingMute > 0) {
            muteUntil = t + pendingMute
            pendingMute = 0.0
        }
        if (delta == null) {
            lastSignal = 0.0
            return emptyList()
        }
        if (wasCalibrating) {
            wasCalibrating = false
            muteUntil = t + MUTE_AFTER_S
        }
        val base = p.baseline!!
        var raw = v - base
        if (recording.isNotEmpty()) recDelta += v - (recBase ?: base)
        lastSignal = delta.norm
        if (p.phoneMoving(t)) {
            // Si se mueve el telefono, el cambio no es del iman.
            delta = Vec3.ZERO
            raw = Vec3.ZERO
        }

        val out = ArrayList<Pair<GestureEvent, Boolean>>()
        val muted = actionsMuted(t)
        var anyActive = false
        val best = bestGesture(delta)
        for ((name, b) in gestures) {
            val d = b.detector
            var suppress = false
            if (best != null && name != best && d.direction != null) {
                val c = d.direction.u dot gestures.getValue(best).detector.direction!!.u
                suppress = (if (d.bipolar) kotlin.math.abs(c) else c) < 0.95
            }
            for (e in d.step(t, delta, raw, p.noise, suppress)) {
                if (e.kind == "drift") p.rebaseline()
                out += e to muted
            }
            anyActive = anyActive || d.active
        }
        p.hold = anyActive
        return out
    }

    /** Sin acciones mientras se calibra, se graba o justo despues. */
    fun actionsMuted(t: Double) = pipeline.calibrating || recording.isNotEmpty() || t < muteUntil

    /** El gesto cuya direccion se parece mas al cambio: dos gestos no se disparan a la vez. */
    private fun bestGesture(delta: Vec3): String? {
        val mag = delta.norm
        if (mag < 1e-9) return null
        var best: String? = null
        var bestC = -2.0
        for ((name, b) in gestures) {
            val d = b.detector
            val u = d.direction?.u ?: continue
            if (d.active || d.aboveSince != null) return name // el que ya empezo manda
            var c = (delta dot u) / mag
            if (d.bipolar) c = kotlin.math.abs(c)
            if (c > bestC) {
                best = name
                bestC = c
            }
        }
        return best
    }

    fun startRecording(label: String): String? {
        if (label.isBlank()) return "Falta el nombre"
        if (pipeline.calibrating) return "Espera: calibrando (deja el celular quieto)"
        recording = label
        recBase = pipeline.baseline
        recDelta.clear()
        return null
    }

    /** Devuelve cuantos ejemplos hay ahora de esa etiqueta. */
    fun stopRecording(): Int {
        val label = recording
        if (label.isEmpty()) return 0
        if (recDelta.size >= MIN_SAMPLES) examples.getOrPut(label) { mutableListOf() } += recDelta.toList()
        recording = ""
        recBase = null
        recDelta.clear()
        pendingMute = MUTE_AFTER_S
        return examples[label]?.size ?: 0
    }

    fun clearExamples(label: String) {
        examples.remove(label)
    }

    /** Arma (o reemplaza, si ya existe con ese nombre) un gesto desde los ejemplos de [label]. */
    fun train(spec: GestureSpec): TrainOutcome {
        val exs = examples[spec.label].orEmpty()
        if (exs.isEmpty()) return TrainOutcome(false, error = "No hay ejemplos de \"${spec.label}\"")
        val dm = DirectionModel.fit(exs)
        val d = EventGestureDetector(spec.name, dm, minOn = spec.minOnMs / 1000.0)
        gestures[spec.name] = BoundGesture(d, spec.label, spec.trigger)
        specs[spec.name] = spec
        updateDirections()
        val thr = d.threshold(pipeline.noise)
        val warning = if (dm.peak < 1.5 * thr) {
            "Señal débil: los ejemplos llegan a %.1f µT y el umbral es %.1f µT. Acerca el imán (2–3 cm del sensor).".format(dm.peak, thr)
        } else {
            null
        }
        return TrainOutcome(true, spec.name, dm.consistency(exs), thr, dm.peak, warning)
    }

    fun remove(name: String) {
        gestures.remove(name)
        specs.remove(name)
        updateDirections()
    }

    /** Polaridad y direccion para la linea base: ambas caras del iman salvo que otro gesto use la contraria. */
    private fun updateDirections() {
        val evs = gestures.values.map { it.detector }.filter { it.direction != null }
        for (d in evs) {
            d.bipolar = evs.none { o -> o !== d && (o.direction!!.u dot d.direction!!.u) < -0.5 }
        }
        pipeline.direction = evs.lastOrNull()?.direction?.u
    }

    companion object {
        /** Segundos sin acciones tras calibrar o terminar de grabar. */
        const val MUTE_AFTER_S = 1.5
        private const val MIN_SAMPLES = 3
    }
}
