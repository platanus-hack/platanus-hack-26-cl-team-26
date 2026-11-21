package cl.magnesense.tracking

import cl.magnesense.detector.Vec3
import kotlin.math.abs

/** Matriz 3×3 (por filas). Solo lo necesario para el rastreo del iman. */
class Mat3(private val a: DoubleArray) {

    init {
        require(a.size == 9)
    }

    operator fun get(r: Int, c: Int): Double = a[r * 3 + c]

    operator fun times(v: Vec3): Vec3 = Vec3(
        a[0] * v.x + a[1] * v.y + a[2] * v.z,
        a[3] * v.x + a[4] * v.y + a[5] * v.z,
        a[6] * v.x + a[7] * v.y + a[8] * v.z,
    )

    operator fun times(o: Mat3): Mat3 = Mat3(DoubleArray(9) { i ->
        val r = i / 3
        val c = i % 3
        this[r, 0] * o[0, c] + this[r, 1] * o[1, c] + this[r, 2] * o[2, c]
    })

    operator fun plus(o: Mat3): Mat3 = Mat3(DoubleArray(9) { a[it] + o.a[it] })

    operator fun times(s: Double): Mat3 = Mat3(DoubleArray(9) { a[it] * s })

    fun transpose(): Mat3 = Mat3(DoubleArray(9) { i -> this[i % 3, i / 3] })

    fun diagonal(): Vec3 = Vec3(a[0], a[4], a[8])

    /** Resuelve this · x = b por eliminacion gaussiana con pivoteo parcial. */
    fun solve(b: Vec3): Vec3 {
        val m = Array(3) { r -> doubleArrayOf(this[r, 0], this[r, 1], this[r, 2]) }
        val v = doubleArrayOf(b.x, b.y, b.z)
        for (col in 0 until 3) {
            val pivot = (col until 3).maxBy { abs(m[it][col]) }
            if (abs(m[pivot][col]) < 1e-30) throw ArithmeticException("matriz singular")
            m[col] = m[pivot].also { m[pivot] = m[col] }
            v[col] = v[pivot].also { v[pivot] = v[col] }
            for (r in col + 1 until 3) {
                val f = m[r][col] / m[col][col]
                for (k in col until 3) m[r][k] -= f * m[col][k]
                v[r] -= f * v[col]
            }
        }
        val x = DoubleArray(3)
        for (r in 2 downTo 0) {
            var s = v[r]
            for (k in r + 1 until 3) s -= m[r][k] * x[k]
            x[r] = s / m[r][r]
        }
        return Vec3(x[0], x[1], x[2])
    }

    companion object {
        val IDENTITY = Mat3(doubleArrayOf(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0))

        fun outer(u: Vec3, v: Vec3) = Mat3(
            doubleArrayOf(
                u.x * v.x, u.x * v.y, u.x * v.z,
                u.y * v.x, u.y * v.y, u.y * v.z,
                u.z * v.x, u.z * v.y, u.z * v.z,
            ),
        )

        fun fromColumns(c0: Vec3, c1: Vec3, c2: Vec3) = Mat3(
            doubleArrayOf(c0.x, c1.x, c2.x, c0.y, c1.y, c2.y, c0.z, c1.z, c2.z),
        )

        fun diag(d: Vec3) = Mat3(doubleArrayOf(d.x, 0.0, 0.0, 0.0, d.y, 0.0, 0.0, 0.0, d.z))
    }
}
