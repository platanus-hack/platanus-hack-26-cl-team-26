package cl.magnesense.ui.access

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.State
import androidx.compose.runtime.produceState
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import cl.magnesense.access.PhoneControl
import cl.magnesense.ui.components.BigButton
import cl.magnesense.ui.components.BigOutlineButton
import cl.magnesense.ui.components.Panel
import cl.magnesense.ui.theme.Palette
import kotlinx.coroutines.delay

/** Si el servicio de accesibilidad del Modo celular esta activo (se revisa cada segundo). */
@Composable
fun rememberPhoneModeEnabled(): State<Boolean> = produceState(PhoneControl.isEnabled) {
    while (true) {
        value = PhoneControl.isEnabled
        delay(1_000)
    }
}

/**
 * Activar el Modo celular: estado del servicio y botones a las pantallas exactas de Android,
 * incluido el paso de "ajustes restringidos" que Android 13+ exige a un APK instalado a mano.
 */
@Composable
fun PhoneModeCard() {
    val context = LocalContext.current
    val enabled = rememberPhoneModeEnabled().value
    Panel {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("Modo celular", style = MaterialTheme.typography.titleLarge, color = Palette.Text)
            Text(
                if (enabled) "✓ Activo: sal de MagneSense y usa estos pulsos en cualquier app."
                else "! Inactivo: hay que activarlo una vez en los ajustes de Android.",
                style = MaterialTheme.typography.bodyLarge,
                color = if (enabled) Palette.Ok else Palette.WarningSoft,
            )
            if (!enabled) {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    Text(
                        "1. Como la app no viene de Play Store, primero: Información de la app → ⋮ (arriba a la derecha) → Permitir ajustes restringidos.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = Palette.Muted,
                    )
                    BigOutlineButton("Abrir información de la app", { openAppDetails(context) }, Modifier.fillMaxWidth())
                }
                Text(
                    "2. En Accesibilidad → Apps instaladas, activa \"MagneSense: control con imán\". Android avisará que puede controlar la pantalla: es lo que permite deslizar por ti. No lee la pantalla.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = Palette.Muted,
                )
                BigButton("Abrir ajustes de accesibilidad", { openAccessibility(context) }, Modifier.fillMaxWidth())
            }
        }
    }
}

private fun openAccessibility(context: Context) {
    runCatching {
        context.startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }
}

private fun openAppDetails(context: Context) {
    runCatching {
        context.startActivity(
            Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:${context.packageName}"))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
        )
    }
}
