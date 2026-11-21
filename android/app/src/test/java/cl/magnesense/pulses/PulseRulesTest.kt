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
    fun whileLockedOnlyUnlockAndAlarmPass() {
        assertTrue(PulseRules.allowedWhileLocked("..."))
        assertTrue(PulseRules.allowedWhileLocked("---"))
        assertFalse(PulseRules.allowedWhileLocked("."))
        assertFalse(PulseRules.allowedWhileLocked("-."))
    }

    @Test
    fun lockCodeIsReservedInEveryProfileAndAlarmIsThreeDashes() {
        for (p in PulseProfile.entries) {
            assertTrue("${p.name} usa el codigo de pausa", p.commands.none { it.code == PulseRules.LOCK_CODE })
            p.commands.filter { it.action == PulseAction.ALARM }.forEach {
                assertTrue("${p.name}: alarma en ${it.code}", it.code == PulseRules.ALARM_CODE)
            }
        }
    }

    @Test
    fun phoneActionsOnlyOutsideMagneSense() {
        assertFalse(PulseRules.phoneActionAllowed(PhoneAction.NEXT, inForeground = true))
        assertFalse(PulseRules.phoneActionAllowed(PhoneAction.CURSOR, inForeground = true))
        assertTrue(PulseRules.phoneActionAllowed(PhoneAction.OPEN_APP, inForeground = true))
        assertTrue(PulseRules.phoneActionAllowed(PhoneAction.BACK, inForeground = false))
    }
}
