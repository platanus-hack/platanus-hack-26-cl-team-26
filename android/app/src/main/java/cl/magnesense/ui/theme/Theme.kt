package cl.magnesense.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

/**
 * Paleta de alto contraste. Los estados nunca se distinguen solo por rojo/verde:
 * se usa ambar (resaltado), azul (correcto) y naranjo (advertencia), siempre con texto.
 */
object Palette {
    val Background = Color(0xFF0E1116)
    val Surface = Color(0xFF171B22)
    val Border = Color(0xFF2A303A)
    val Text = Color(0xFFF2F4F7)
    val Muted = Color(0xFFA7B0BD)
    val Highlight = Color(0xFFFFC23D)
    val OnHighlight = Color(0xFF14110A)
    val Ok = Color(0xFF5AA9FF)
    val Warning = Color(0xFFFF8A3D)
    val WarningSoft = Color(0xFFFFB17A)
}

private val colors = darkColorScheme(
    primary = Palette.Highlight,
    onPrimary = Palette.OnHighlight,
    secondary = Palette.Ok,
    onSecondary = Palette.Background,
    tertiary = Palette.Warning,
    background = Palette.Background,
    onBackground = Palette.Text,
    surface = Palette.Surface,
    onSurface = Palette.Text,
    surfaceVariant = Palette.Surface,
    onSurfaceVariant = Palette.Muted,
    outline = Palette.Border,
    error = Palette.Warning,
    onError = Palette.Background,
)

private val typography = Typography(
    displayMedium = TextStyle(fontSize = 44.sp, fontWeight = FontWeight.Bold, lineHeight = 50.sp),
    headlineMedium = TextStyle(fontSize = 30.sp, fontWeight = FontWeight.Bold, lineHeight = 36.sp),
    titleLarge = TextStyle(fontSize = 24.sp, fontWeight = FontWeight.SemiBold, lineHeight = 30.sp),
    titleMedium = TextStyle(fontSize = 20.sp, fontWeight = FontWeight.SemiBold, lineHeight = 26.sp),
    bodyLarge = TextStyle(fontSize = 20.sp, lineHeight = 28.sp),
    bodyMedium = TextStyle(fontSize = 17.sp, lineHeight = 24.sp),
    labelLarge = TextStyle(fontSize = 18.sp, fontWeight = FontWeight.SemiBold),
)

@Composable
fun MagneSenseTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = colors, typography = typography, content = content)
}
