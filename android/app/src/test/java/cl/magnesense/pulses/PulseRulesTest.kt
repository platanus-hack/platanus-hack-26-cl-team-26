package cl.magnesense.pulses

import cl.magnesense.access.PhoneAction
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PulseRulesTest {

    @Test
    fun calibratingInsideTheAppPausesPulses() {
        assertFalse(PulseRules.enabled(pulsesMode = true, teaching = false, inForeground = true, magnetBusy = true))
    }

    @Test
    fun otherScreensAndOtherAppsKeepWorking() {
        assertTrue(PulseRules.enabled(pulsesMode = true, teaching = false, inForeground = true, magnetBusy = false))
        // Fuera de la app no hay calibracion en curso aunque la ultima pantalla fuera 3D.
        assertTrue(PulseRules.enabled(pulsesMode = true, teaching = false, inForeground = false, magnetBusy = true))
    }

    @Test
    fun otherModesAndTeachingStillDisable() {
        assertFalse(PulseRules.enabled(pulsesMode = false, teaching = false, inForeground = false, magnetBusy = false))
        assertFalse(PulseRules.enabled(pulsesMode = true, teaching = true, inForeground = false, magnetBusy = false))
    }

    @Test
    fun phoneActionsOnlyOutsideMagneSense() {
        assertFalse(PulseRules.phoneActionAllowed(PhoneAction.NEXT, inForeground = true))
        assertFalse(PulseRules.phoneActionAllowed(PhoneAction.CURSOR, inForeground = true))
        assertTrue(PulseRules.phoneActionAllowed(PhoneAction.OPEN_APP, inForeground = true))
        assertTrue(PulseRules.phoneActionAllowed(PhoneAction.BACK, inForeground = false))
    }
}
