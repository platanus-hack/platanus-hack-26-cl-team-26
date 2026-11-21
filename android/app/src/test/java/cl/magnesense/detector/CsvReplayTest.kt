package cl.magnesense.detector

import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File
import java.util.Locale

/**
 * Herramienta de repeticion: pasa las sesiones grabadas por server.py (data/session_*.csv,
 * columnas t,x,y,z,uncal,...) por el detector de Kotlin e informa activaciones por minuto.
 *
 * Usa los primeros 10 s de cada sesion como calibracion en reposo (sin calibracion del iman,
 * asi que el chequeo de direccion queda apagado). Si no hay sesiones, la prueba se omite.
 *
 *   ./gradlew :app:testDebugUnitTest --tests '*CsvReplayTest*' -i
 *   (o definir MAGNESENSE_DATA=/ruta/a/data)
 */
class CsvReplayTest {

    @Test
    fun replayRecordedSessions() {
        val dir = System.getenv("MAGNESENSE_DATA")?.let(::File) ?: findDataDir()
        val sessions = dir?.listFiles { f -> f.name.startsWith("session_") && f.name.endsWith(".csv") }
            ?.sortedBy { it.name }.orEmpty()
        assumeTrue("No hay sesiones CSV en data/", sessions.isNotEmpty())

        println("Sesion                               muestras  minutos  activaciones  por minuto  ignorados")
        for (file in sessions) {
            val r = replay(file) ?: continue
            println(
                String.format(
                    Locale.US, "%-36s %8d %8.2f %13d %11.2f %10d",
                    file.name, r.samples, r.minutes, r.activations, r.activations / r.minutes.coerceAtLeast(1e-9), r.ignored,
                ),
            )
        }
    }

    private data class Result(val samples: Int, val minutes: Double, val activations: Int, val ignored: Int)

    private fun replay(file: File): Result? {
        val lines = file.readLines()
        if (lines.size < 3) return null
        val header = lines.first().split(',')
        val it = header.indexOf("t")
        val ix = header.indexOf("x")
        val iy = header.indexOf("y")
        val iz = header.indexOf("z")
        if (listOf(it, ix, iy, iz).any { it < 0 }) return null

        val detector = Detector()
        detector.startRestCalibration()
        var activations = 0
        var ignored = 0
        var first = Double.NaN
        var last = Double.NaN
        var n = 0
        for (line in lines.drop(1)) {
            val c = line.split(',')
            val t = c.getOrNull(it)?.toDoubleOrNull() ?: continue
            val v = Vec3(c[ix].toDoubleOrNull() ?: continue, c[iy].toDoubleOrNull() ?: continue, c[iz].toDoubleOrNull() ?: continue)
            if (first.isNaN()) first = t
            last = t
            n++
            for (e in detector.processMagnetometer(t, v)) {
                when (e.type) {
                    EventType.ACTIVATED -> activations++
                    EventType.IGNORED -> ignored++
                    else -> Unit
                }
            }
        }
        if (n == 0) return null
        val minutes = ((last - first - detector.config.restCalibrationSeconds) / 60.0).coerceAtLeast(0.0)
        return Result(n, minutes, activations, ignored)
    }

    /** Busca data/ subiendo desde el directorio de trabajo (app/ -> android/ -> repo). */
    private fun findDataDir(): File? {
        var d: File? = File("").absoluteFile
        repeat(4) {
            val candidate = File(d, "data")
            if (candidate.isDirectory) return candidate
            d = d?.parentFile
        }
        return null
    }
}
