// La página es la cara; terreno/servidor.py (FastAPI) es la API: cruza los datos por comuna, calcula el
// corredor con y sin capturas en terreno y sirve las fotos y los audios de aves. Next le reenvía estas rutas,
// y también /captura: la página del teléfono (foto, video y escuchar aves), para tener un solo enlace público.
const TERRENO = process.env.TERRENO_URL ?? "http://127.0.0.1:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return ["/api/:ruta*", "/fotos/:ruta*", "/videos/:ruta*", "/audios/:ruta*", "/captura"].map((source) => ({
      source, destination: `${TERRENO}${source}`,
    }));
  },
};
export default nextConfig;
