import { readFileSync } from "node:fs";
import path from "node:path";
import Pagina from "@/components/Pagina";

// El mapa y las cifras vienen del servidor de terreno (terreno/servidor.py) a través de /api.
// Aquí solo va la serie mensual de la ciudad para las barras del histórico (web/scripts/exportar_datos.py).
export default function Home() {
  const serie = JSON.parse(readFileSync(path.join(process.cwd(), "public", "data", "historico.json"), "utf8"));
  return <Pagina serie={serie} />;
}
