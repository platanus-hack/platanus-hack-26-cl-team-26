// La página es la cara; terreno/servidor.py (FastAPI) es la API: cruza los datos por comuna, calcula el
// corredor con y sin capturas en terreno y sirve las fotos y los audios de aves.
//
// Dos formas de correrla:
// · Desarrollo (npm run dev / npm start): Next reenvía /api, /fotos, /videos, /audios y /captura al servidor de
//   terreno (TERRENO_URL, por defecto http://127.0.0.1:8000).
// · Despliegue (npm run exportar): la página se exporta como archivos estáticos en web/out y el mismo servidor de
//   terreno los sirve en «/». Un solo servicio y un solo enlace: la página, la API y /captura (el teléfono).
const TERRENO = process.env.TERRENO_URL ?? "http://127.0.0.1:8000";
// npm pone el nombre del script en npm_lifecycle_event: así funciona igual en Windows, Mac y Linux.
const exportar = process.env.npm_lifecycle_event === "exportar" || process.env.EXPORTAR === "1";

/** @type {import('next').NextConfig} */
const nextConfig = exportar
  ? { reactStrictMode: true, output: "export", images: { unoptimized: true } }
  : {
      reactStrictMode: true,
      async rewrites() {
        return ["/api/:ruta*", "/fotos/:ruta*", "/videos/:ruta*", "/audios/:ruta*", "/captura"].map((source) => ({
          source, destination: `${TERRENO}${source}`,
        }));
      },
    };
export default nextConfig;
