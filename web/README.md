# Viridis (antes VerdeH3) · página web (experimental)

Concepto B, "página que se recorre": portada con la rama ilustrada, y las secciones Datos clave,
Planificar, Santiago conectado y Fuentes, con la paleta Bioentidad (crema, oliva #4F6E31, salvia) y la capa de
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
- **El viaje del picaflor**: un cortometraje en SVG de unos 45 s (parte solo al llegar). Acto 1: el picaflor
  cruza del Cerro Renca al San Cristóbal por la ciudad real en línea recta (cada cuadra es un edificio o un árbol
  según su copa), con calor y cansancio que crecen con las cuadras seguidas sin árboles. Acto 2: la ruta para
  aves con el corredor plantado, árboles que brotan y flores (`public/data/viaje.json`).
- **Santiago conectado**: un control de 0 a 100 km y «Ver crecer la red» sobre todo Santiago, con las islas que une,
  las personas a una cuadra y la fauna registrada (`public/data/red.json`, de `python red_conectada.py`).

`historico.json` (lo usa `/fuentes`), `fauna.json`, `red.json` y `viaje.json` son estáticos. Para regenerar el primero, desde la raíz del repo:

```bash
python web/scripts/exportar_datos.py
```

## Movimiento

Las secciones entran al hacer scroll, la rama brota en la portada, las cifras cuentan hasta su valor,
el mapa cruza capas y vuela entre comunas, y el corredor nuevo aparece desde transparente. Con
`prefers-reduced-motion` todo eso queda quieto.

Capturas de pantalla en `capturas/`.
