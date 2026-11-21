package cl.magnesense.detector

import kotlin.math.sqrt

/** Vector 3D inmutable (µT para el magnetometro, rad/s para el giroscopio). */
data class Vec3(val x: Double, val y: Double, val z: Double) {
    operator fun plus(o: Vec3) = Vec3(x + o.x, y + o.y, z + o.z)
    operator fun minus(o: Vec3) = Vec3(x - o.x, y - o.y, z - o.z)
    operator fun times(s: Double) = Vec3(x * s, y * s, z * s)
    operator fun div(s: Double) = Vec3(x / s, y / s, z / s)

    infix fun dot(o: Vec3): Double = x * o.x + y * o.y + z * o.z

    val norm: Double get() = sqrt(this dot this)

    /** Vector unitario, o ZERO si el vector es (casi) nulo. */
    fun normalized(): Vec3 {
        val n = norm
        return if (n < 1e-12) ZERO else this / n
    }

    /** Interpolacion exponencial hacia [target] con factor [a] en [0, 1]. */
    fun approach(target: Vec3, a: Double): Vec3 = this + (target - this) * a

    fun maxAbs(): Double = maxOf(kotlin.math.abs(x), kotlin.math.abs(y), kotlin.math.abs(z))

    companion object {
        val ZERO = Vec3(0.0, 0.0, 0.0)
    }
}
