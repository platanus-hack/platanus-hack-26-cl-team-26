package cl.magnesense

import android.Manifest
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import cl.magnesense.sensor.SensorService
import cl.magnesense.ui.AppRoot
import cl.magnesense.ui.intro.MagnetGateScreen
import cl.magnesense.ui.theme.MagneSenseTheme
import cl.magnesense.ui.theme.Palette

class MainActivity : ComponentActivity() {

    private val notificationPermission =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { /* el servicio funciona igual */ }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        SensorService.start(this)
        setContent {
            MagneSenseTheme {
                Box(Modifier.fillMaxSize().background(Palette.Background).safeDrawingPadding()) {
                    val app = application as MagneSenseApp
                    // Intro "puerta magnetica" en cada apertura: se entra acercando el iman.
                    var unlocked by remember { mutableStateOf(false) }
                    SideEffect { app.gateShowing = !unlocked }
                    if (unlocked) AppRoot(app) else MagnetGateScreen(app, onEnter = { unlocked = true })
                }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        (application as MagneSenseApp).inForeground = true
    }

    override fun onPause() {
        (application as MagneSenseApp).inForeground = false
        super.onPause()
    }
}
