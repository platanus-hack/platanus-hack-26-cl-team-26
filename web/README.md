# Viridis (antes VerdeH3) · página web (experimental)

Concepto B, "página que se recorre": portada con la rama ilustrada, y las secciones Datos clave,
Planificar, Histórico y Fuentes, con la paleta Bioentidad (crema, oliva #4F6E31, salvia) y la capa de
calor en ocre. Next.js 16 + MapLibre, sobre Carto Positron teñido.

## Correr

El mapa, las comunas y el corredor vienen del servidor (`terreno/servidor.py`), que cruza los datos por
comuna. Next reenvía `/api` a ese servidor (`TERRENO_URL`, por defecto `http://127.0.0.1:8000`).

```bash
pip install -r requirements.txt               # desde la raíz del repo
python -m terreno.servidor --puerto 8000      # o: cd web && npm run api
cd web
npm install
npm run dev                                   # http://localhost:3000
```

Producción: `npm run build && npm start`. Si el servidor está en otra máquina:
`TERRENO_URL=http://host:8000 npm run build`.

## Qué muestra

- **Datos clave**: las 34 comunas del Gran Santiago juntas, o las que se elijan con doble clic o el lápiz.
  Capas de calor, árboles, personas, aves y abejas. El calor es el suelo, combinado con la máxima del
  aire (70 % suelo y 30 % aire) donde hay al menos 5 barrios con confianza alta o media. Aves y abejas salen
  de `public/data/fauna.json` (GBIF, `python fauna_gbif.py` desde la raíz).
- **Planificar**: largo y pesos del corredor (los recalcula el servidor), para humanos, aves, abejas o mixto,
  la fauna registrada en los barrios que cruza y exportar los tramos en GeoJSON.
- **Histórico**: barras mensuales del suelo (`public/data/historico.json`); al elegir un mes el servidor
  promedia desde ahí hasta hoy.

`historico.json` y `fauna.json` son estáticos. Para regenerarlo, desde la raíz del repo:

```bash
python web/scripts/exportar_datos.py
```

## Movimiento

Las secciones entran al hacer scroll, la rama brota en la portada, las cifras cuentan hasta su valor,
el mapa cruza capas y vuela entre comunas, y el corredor nuevo aparece desde transparente. Con
`prefers-reduced-motion` todo eso queda quieto.

Capturas de pantalla en `capturas/`.
