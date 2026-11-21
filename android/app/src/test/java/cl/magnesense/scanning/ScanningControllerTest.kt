package cl.magnesense.scanning

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ScanningControllerTest {

    private val options = listOf(
        ScanOption("luz", "Luz"),
        ScanOption("ventilador", "Ventilador"),
        ScanOption("tv", "Televisión"),
        ScanOption("cuidador", "Llamar cuidador", critical = true, confirmPrompt = "¿Llamar a tu cuidador?"),
    )

    private class Recorder : ScanListener {
        val spoken = mutableListOf<String>()
        val feedback = mutableListOf<FeedbackKind>()
        val selected = mutableListOf<String>()
        override fun speak(text: String, queue: Boolean) { spoken += text }
        override fun feedback(kind: FeedbackKind) { feedback += kind }
        override fun onSelected(option: ScanOption) { selected += option.id }
    }

    private val rec = Recorder()
    private val scan = ScanningController(rec, options, stepMs = 2_000)
    private var now = 0L

    private fun advance(ms: Long) {
        val end = now + ms
        while (now < end) {
            now += 50
            scan.tick(now)
        }
    }

    @Test
    fun firstActivationArmsAndSecondSelectsHighlighted() {
        scan.onActivation(now)
        assertEquals(ScanMode.SCANNING, scan.state.value.mode)
        assertEquals("Luz", rec.spoken.last())
        advance(2_000)
        assertEquals("ventilador", scan.state.value.highlighted?.id)
        assertEquals("Ventilador", rec.spoken.last())
        scan.onActivation(now)
        assertEquals(listOf("ventilador"), rec.selected)
        assertEquals(ScanMode.IDLE, scan.state.value.mode)
        assertEquals(listOf(FeedbackKind.ARMED, FeedbackKind.SELECTED), rec.feedback)
    }

    @Test
    fun stopsAfterTwoIdleRounds() {
        scan.onActivation(now)
        advance(2 * 4 * 2_000L - 100)
        assertEquals(ScanMode.SCANNING, scan.state.value.mode)
        advance(200)
        assertEquals(ScanMode.IDLE, scan.state.value.mode)
        assertTrue(rec.selected.isEmpty())
    }

    @Test
    fun criticalOptionNeedsConfirmation() {
        scan.onActivation(now)
        advance(3 * 2_000L)
        assertEquals("cuidador", scan.state.value.highlighted?.id)
        scan.onActivation(now)
        assertEquals(ScanMode.CONFIRMING, scan.state.value.mode)
        assertTrue(rec.spoken.contains("¿Llamar a tu cuidador?"))
        assertEquals(0, scan.state.value.confirmIndex)
        scan.onActivation(now + 500)
        assertEquals(listOf("cuidador"), rec.selected)
    }

    @Test
    fun confirmationCanBeDeclined() {
        scan.onActivation(now)
        advance(3 * 2_000L)
        scan.onActivation(now)
        advance(3_600) // pregunta + paso a "No"
        assertEquals(1, scan.state.value.confirmIndex)
        scan.onActivation(now)
        assertTrue(rec.selected.isEmpty())
        assertEquals(FeedbackKind.CANCELLED, rec.feedback.last())
    }

    @Test
    fun confirmationAutoCancelsAfterTenSeconds() {
        scan.onActivation(now)
        advance(3 * 2_000L)
        scan.onActivation(now)
        advance(10_050)
        assertEquals(ScanMode.IDLE, scan.state.value.mode)
        assertTrue(rec.selected.isEmpty())
        assertEquals("Cancelado", rec.spoken.last())
    }
}
