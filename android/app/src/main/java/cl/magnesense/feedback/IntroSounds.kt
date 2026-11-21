package cl.magnesense.feedback

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import kotlin.math.PI
import kotlin.math.exp
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.tanh
import kotlin.random.Random

/**
 * Sonido de ciencia ficcion para la intro, sintetizado en vivo (sin archivos):
 * - un zumbido grave que crece y sube de tono con la carga ([level], [progress]);
 * - un "ping" con cada onda ([ping]);
 * - un "power-up" al completar ([finale]): barrido ascendente, rafaga y un acorde brillante.
 *
 * Un solo AudioTrack en modo stream, alimentado por un hilo; los parametros se suavizan
 * muestra a muestra para que no haya chasquidos.
 */
class IntroSounds {

    /** Intensidad del iman, 0..1. */
    @Volatile
    var level = 0f

    /** Avance de la carga, 0..1. */
    @Volatile
    var progress = 0f

    @Volatile
    private var stopRequested = false

    @Volatile
    private var pingRequested = false

    @Volatile
    private var finaleRequested = false

    private var thread: Thread? = null

    fun start() {
        if (thread != null) return
        thread = Thread(::run, "magnesense-intro-sound").apply {
            isDaemon = true
            start()
        }
    }

    fun ping() {
        pingRequested = true
    }

    fun finale() {
        finaleRequested = true
    }

    /** Detiene el sonido; si el power-up esta sonando, lo deja terminar. */
    fun stop() {
        stopRequested = true
    }

    private fun run() {
        val track = runCatching {
            val minBuf = AudioTrack.getMinBufferSize(SR, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT)
            AudioTrack.Builder()
                .setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_GAME)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                        .build(),
                )
                .setAudioFormat(
                    AudioFormat.Builder()
                        .setSampleRate(SR)
                        .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                        .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                        .build(),
                )
                .setTransferMode(AudioTrack.MODE_STREAM)
                .setBufferSizeInBytes(maxOf(minBuf, BLOCK * 4))
                .build()
        }.getOrNull() ?: return
        runCatching { track.play() }
        val buf = ShortArray(BLOCK)
        val synth = Synth()
        try {
            while (!synth.finished(stopRequested)) {
                if (pingRequested) {
                    pingRequested = false
                    synth.startPing()
                }
                if (finaleRequested) {
                    finaleRequested = false
                    synth.startFinale()
                }
                for (i in 0 until BLOCK) buf[i] = synth.next(level, progress, stopRequested)
                track.write(buf, 0, BLOCK)
            }
        } finally {
            runCatching { track.stop() }
            track.release()
        }
    }

    /** Estado de la sintesis (solo lo usa el hilo de audio). */
    private class Synth {
        private val random = Random(7)
        private var lvl = 0.0
        private var prog = 0.0
        private var master = 1.0
        private var phDrone = 0.0
        private var phDetune = 0.0
        private var phShimmer = 0.0
        private var phLfo = 0.0
        private var pingPos = -1
        private var phPing = 0.0
        private var finalePos = -1
        private var phSweep = 0.0
        private val phChord = DoubleArray(CHORD.size)
        private var noiseLp = 0.0

        fun startPing() {
            pingPos = 0
        }

        fun startFinale() {
            finalePos = 0
        }

        fun finished(stopRequested: Boolean): Boolean =
            stopRequested && finalePos < 0 && master < 0.001

        fun next(level: Float, progress: Float, stopping: Boolean): Short {
            lvl += (level - lvl) * 0.0004
            prog += (progress - prog) * 0.0008
            // Al terminar (o al cerrar) el zumbido se apaga suave.
            val target = if (stopping || finalePos >= 0) 0.0 else 1.0
            master += (target - master) * 0.0003

            // Zumbido: grave tipo organo con una segunda voz desafinada (batido) que sube con la carga.
            val fDrone = 55.0 * (1.0 + prog * 1.2)
            phDrone += TWO_PI * fDrone / SR
            phDetune += TWO_PI * fDrone * 1.008 / SR
            val drone = sin(phDrone) + 0.5 * sin(2 * phDrone) + 0.3 * sin(3 * phDetune) + 0.4 * sin(phDetune)
            // Brillo: tono que sube de 220 a 880 Hz con tremolo.
            phLfo += TWO_PI * (5.0 + 4.0 * prog) / SR
            phShimmer += TWO_PI * (220.0 * 2.0.pow(prog * 2)) / SR
            val shimmer = sin(phShimmer) * (0.5 + 0.5 * sin(phLfo))
            var s = master * ((0.035 + 0.25 * lvl) * drone * 0.45 + 0.22 * lvl * shimmer)

            if (pingPos >= 0) {
                val x = pingPos.toDouble() / SR
                phPing += TWO_PI * (1600.0 - 800.0 * (x / PING_S)) / SR
                s += 0.18 * exp(-x * 28) * sin(phPing)
                if (++pingPos > (PING_S * SR).toInt()) pingPos = -1
            }

            if (finalePos >= 0) {
                val x = finalePos.toDouble() / SR
                // Barrido ascendente con rafaga de ruido filtrado.
                if (x < SWEEP_S) {
                    val k = x / SWEEP_S
                    phSweep += TWO_PI * (180.0 * 2.0.pow(k * 3.5)) / SR
                    noiseLp += (random.nextDouble(-1.0, 1.0) - noiseLp) * (0.02 + 0.3 * k)
                    s += k * k * (0.3 * sin(phSweep) + 0.25 * noiseLp)
                }
                // Acorde brillante que se desvanece.
                if (x >= SWEEP_S * 0.85) {
                    val y = x - SWEEP_S * 0.85
                    val env = (y / 0.02).coerceAtMost(1.0) * exp(-y * 2.6)
                    var chord = 0.0
                    for (i in CHORD.indices) {
                        phChord[i] += TWO_PI * CHORD[i] / SR
                        chord += sin(phChord[i]) / (i + 1.5)
                    }
                    s += 0.42 * env * chord
                }
                if (++finalePos > (FINALE_S * SR).toInt()) finalePos = -1
            }
            return (tanh(s * 1.4) * 0.8 * Short.MAX_VALUE).toInt().toShort()
        }
    }

    private companion object {
        const val SR = 44_100
        const val BLOCK = 512
        const val TWO_PI = 2 * PI
        const val PING_S = 0.14
        const val SWEEP_S = 0.55
        const val FINALE_S = 2.2
        /** Do mayor con octava y quinta arriba: suena a "acceso concedido". */
        val CHORD = doubleArrayOf(523.25, 659.25, 783.99, 1046.5, 1567.98)
    }
}
