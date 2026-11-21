# VerdeH3 · página web (experimental)

Concepto B, "página que se recorre": portada con la rama ilustrada, y las secciones El calor ahora,
Planificar, Histórico y Fuentes, con la paleta Bioentidad (crema, oliva #4F6E31, salvia) y la capa de
calor en ocre. Next.js 16 + MapLibre, sobre Carto Positron teñido.

## Correr

La página no guarda datos propios: el mapa, las comunas y el corredor vienen del servidor de terreno
(`terreno/servidor.py`, de `feat/integracion-terreno`), que cruza los datos por comuna. Next reenvía
`/api`, `/fotos` y `/videos` a ese servidor (`TERRENO_URL`, por defecto `http://127.0.0.1:8000`).

```bash
pip install -r requirements.txt               # desde la raíz del repo
python -m terreno.servidor --puerto 8000      # o: cd web && npm run api
cd web
npm install
npm run dev                                   # http://localhost:3000
```

Producción: `npm run build && npm start`. Si el servidor de terreno está en otra máquina:
`TERRENO_URL=http://host:8000 npm run build`.

## Qué muestra

- **El calor ahora**: las 34 comunas del Gran Santiago juntas, o una comuna y sus vecinas (se tocan en el
  mapa, igual que en `terreno/static/mapa.html`). Capas de calor, copa de árboles y personas. El calor es
  el índice 0,6 suelo + 0,4 aire donde hay sensores con confianza alta o media; si no, solo suelo.
- **Planificar**: largo y pesos del corredor (los recalcula el servidor), corredor actual contra el de
  sin capturas en terreno, capturas con su foto, y exportar los tramos en GeoJSON.
- **Histórico**: barras mensuales del suelo (`public/data/historico.json`); al elegir un mes el servidor
  promedia desde ahí hasta hoy.

`historico.json` es lo único estático. Para regenerarlo, desde la raíz del repo:

```bash
python web/scripts/exportar_datos.py
```

## Movimiento

Las secciones entran al hacer scroll, la rama brota en la portada, las cifras cuentan hasta su valor,
el mapa cruza capas y vuela entre comunas, y el corredor nuevo aparece desde transparente. Con
`prefers-reduced-motion` todo eso queda quieto.

Capturas en `capturas/`.
