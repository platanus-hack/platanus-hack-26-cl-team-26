# VerdeH3 · página web (experimental)

Concepto B, "página que se recorre": portada con la rama ilustrada, y las secciones El calor ahora,
Planificar, Histórico y Fuentes, con la paleta Bioentidad (crema, oliva #4F6E31, salvia) y la capa de
calor en ocre. Next.js 16 + MapLibre, sobre el mismo mapa base que `app.py` (Carto Positron), teñido.

## Correr

```bash
cd web
npm install
npm run dev        # http://localhost:3000
```

Producción: `npm run build && npm start`.

## Datos

Todo sale de `data/` (los mismos parquet que usa `app.py`), exportado a JSON estático en
`web/public/data/`. Para regenerarlo, desde la raíz del repo y con el entorno de `optimizer.py`:

```bash
python web/scripts/exportar_datos.py
```

- `hexes.json`: las 279 cuadras de Cerro Navia y Providencia (`santiago_h3.parquet`), con la urgencia de `solve_corridor`.
- `vivo.json`: aire en vivo por barrio (`live_h3.parquet`) y sensores (`web_sensors.json`).
- `historico.json`: suelo por cuadra y mes, 2023-01 a 2026-11 (`historico_h3.parquet`); se pide al llegar a esa sección.
- `cifras.json`: `cifras_pitch.json` más el corredor de referencia (40/40/20, 3 km): 13.295 personas contra 8.334 al azar.

## Corredor en el navegador

`lib/optimizador.ts` es un port de `optimizer.py` (urgencia, Dijkstra desde los parques, tramos y red
continua), así que "Recalcular corredor" funciona sin servidor. Con los pesos por defecto la página
muestra las cifras exactas de Python. `npm test` compara el port con esa referencia (mismos hexágonos,
km y personas). El trazado al azar usa otro generador que `random.Random(0)`, así que esa cifra puede
variar un poco al recalcular.

## Movimiento

Las secciones entran al hacer scroll, la rama brota en la portada, las cifras cuentan hasta su valor,
el mapa cruza capas y vuela entre comunas, y el corredor nuevo aparece desde transparente. Con
`prefers-reduced-motion` todo eso queda quieto.

Capturas en `capturas/`.
