package cl.magnesense.pulses

import kotlin.math.max
import kotlin.math.sqrt

/** Un evento del decodificador. */
sealed interface PulseEvent {
    /** Un pulso: "." o "-" ("?" mientras se aprende el ritmo). */
    data class Pulse(val sym: Char, val dur: Double) : PulseEvent

    /** Se cerro una secuencia (silencio >= letterGap). [letter] es la letra Morse, si existe. */
    data class Code(val code: String, val letter: String?) : PulseEvent

    /** Pausa larga: separa palabras. */
    data object Space : PulseEvent

    /** Termino "aprender mi ritmo". */
    data class Timing(val ok: Boolean, val dotMax: Double, val short: Double, val long: Double) : PulseEvent
}

/**
 * Convierte pulsos del iman en secuencias de puntos y rayas, y estas en comandos o letras Morse
 * (port de PulseDecoder en pulsos.py). Solo depende del tiempo, no de la trayectoria del iman.
 *
 * Recibe la duracion de cada pulso ya medida desde que la senal cruzo el umbral ([onPulse]) y,
 * con cada muestra, si el iman esta activo ([tick]) para medir los silencios.
 */
class PulseDecoder(
    /** s: un pulso mas corto es punto, mas largo es raya. */
    var dotMax: Double = 0.40,
    /** s: pulsos mas breves se ignoran (ruido, fasciculaciones). */
    val minPulse: Double = 0.06,
    /** s de silencio que cierran una secuencia. */
    var letterGap: Double = 0.9,
    /** s de silencio que separan palabras (Morse). */
    val wordGap: Double = 2.5,
) {
    /** Secuencia en curso, por ejemplo ".-". */
    var symbols = ""
        private set
    private var tFall: Double? = null
    private var spaceDone = true
    private var timing: MutableList<Double>? = null
    private var timingN = 0

    val learning: Boolean get() = timing != null
    val learnedCount: Int get() = timing?.size ?: 0
    val learnTotal: Int get() = 2 * timingN

    fun reset() {
        symbols = ""
        tFall = null
        spaceDone = true
        timing = null
    }

    /** La persona hace [n] pulsos cortos y despues [n] largos; se ajusta [dotMax] a su ritmo. */
    fun startTiming(n: Int = 3) {
        timing = mutableListOf()
        timingN = n
        symbols = ""
    }

    fun onPulse(t: Double, dur: Double): List<PulseEvent> {
        if (dur < minPulse) return emptyList()
        tFall = t
        val learn = timing
        if (learn != null) {
            learn += dur
            val ev = mutableListOf<PulseEvent>(PulseEvent.Pulse('?', dur))
            if (learn.size >= 2 * timingN) {
                val short = learn.take(timingN).average()
                val long = learn.drop(timingN).average()
                // Si no hay diferencia clara, no se cambia.
                val ok = long > short * 1.3
                if (ok) {
                    dotMax = round3(sqrt(short * long))
                    letterGap = round3(max(0.7, 2.0 * dotMax))
                }
                timing = null
                spaceDone = true
                ev += PulseEvent.Timing(ok, dotMax, short, long)
            }
            return ev
        }
        val sym = if (dur < dotMax) '.' else '-'
        symbols += sym
        spaceDone = false
        return listOf(PulseEvent.Pulse(sym, dur))
    }

    /** Llamar con cada muestra. Con el iman lejos, cierra secuencias y palabras por silencio. */
    fun tick(t: Double, active: Boolean): List<PulseEvent> {
        val fall = tFall ?: return emptyList()
        if (active || timing != null) return emptyList()
        val quiet = t - fall
        if (symbols.isNotEmpty() && quiet >= letterGap) {
            val code = symbols
            symbols = ""
            return listOf(PulseEvent.Code(code, MORSE[code]))
        }
        if (symbols.isEmpty() && !spaceDone && quiet >= wordGap) {
            spaceDone = true
            return listOf(PulseEvent.Space)
        }
        return emptyList()
    }

    companion object {
        val MORSE = mapOf(
            ".-" to "A", "-..." to "B", "-.-." to "C", "-.." to "D", "." to "E", "..-." to "F", "--." to "G", "...." to "H",
            ".." to "I", ".---" to "J", "-.-" to "K", ".-.." to "L", "--" to "M", "-." to "N", "---" to "O", ".--." to "P",
            "--.-" to "Q", ".-." to "R", "..." to "S", "-" to "T", "..-" to "U", "...-" to "V", ".--" to "W", "-..-" to "X",
            "-.--" to "Y", "--.." to "Z", "--.--" to "Ñ",
            ".----" to "1", "..---" to "2", "...--" to "3", "....-" to "4", "....." to "5",
            "-...." to "6", "--..." to "7", "---.." to "8", "----." to "9", "-----" to "0",
        )

        /** ". -" como "• —" para mostrar y para el historial. */
        fun pretty(code: String) = code.map { if (it == '.') "•" else "—" }.joinToString(" ")

        private fun round3(x: Double) = Math.round(x * 1000) / 1000.0
    }
}
