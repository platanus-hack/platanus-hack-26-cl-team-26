import { readFileSync } from "node:fs";
import path from "node:path";
import Pagina from "@/components/Pagina";

// Datos reales exportados por web/scripts/exportar_datos.py; el histórico se pide aparte, al llegar a su sección.
function leer(nombre: string) {
  return JSON.parse(readFileSync(path.join(process.cwd(), "public", "data", nombre), "utf8"));
}

export default function Home() {
  return <Pagina hexes={leer("hexes.json")} vivo={leer("vivo.json")} cifras={leer("cifras.json")} />;
}
