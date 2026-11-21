# Viridis

**Donde se necesita el verde: calor, copa de árboles y personas, cuadra por cuadra, para decidir por dónde plantar el próximo corredor verde de Santiago.**

## El problema

Santiago se calienta de forma desigual. El oriente tiene copa de árboles y parques; el poniente y el sur tienen asfalto, menos sombra y más gente expuesta. Los municipios plantan con presupuestos chicos y sin una forma simple de ver dónde un árbol alivia más.

## Cómo funciona

- Divide las 34 comunas del Gran Santiago en una grilla hexagonal H3, del tamaño de una cuadra.
- En cada cuadra junta el calor del suelo (Landsat), la copa de árboles (modelo propio sobre Sentinel-2) y la población (Censo 2024), más la cercanía a colegios, consultorios, metro y paraderos.
- Con eso calcula un índice de urgencia: 40 % calor, 40 % falta de copa y 20 % personas, con pesos que se pueden mover.
- Traza el corredor verde óptimo que une parques existentes pasando por las cuadras más urgentes, y muestra cuánto cambia el promedio de lo elegido.
- Se puede filtrar por comuna o encerrar una zona con un lápiz sobre el mapa, y comparar cada comuna contra el promedio de Santiago.
- En terreno, una foto desde el celular corrige la copa estimada; Claude revisa que la foto sirva antes de usarla.

## Para quién

Equipos de medio ambiente y planificación de municipios, juntas de vecinos y organizaciones que impulsan arbolado urbano y necesitan justificar dónde plantar primero.

## Por qué importa

Cada metro de sombra cuenta más donde hace más calor, hay menos árboles y vive más gente. Viridis pone esa cuenta a la vista, cuadra por cuadra, para que el verde llegue donde se necesita.
