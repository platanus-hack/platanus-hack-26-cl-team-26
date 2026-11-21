// Compara el port en TypeScript con el corredor de referencia que exporta optimizer.py.
// Correr: npm test  (después de npm run datos)
import { readFileSync } from "node:fs";
import { solveCorridor, urgencia, type Barrio, type Hex } from "../lib/optimizador.ts";

const leer = (f: string) => JSON.parse(readFileSync(new URL(`../public/data/${f}`, import.meta.url), "utf8"));
const hexes: Hex[] = leer("hexes.json");
const vivo: { barrios: Barrio[] } = leer("vivo.json");
const ref = leer("cifras.json").referencia;

const U = urgencia(hexes, 0.4, 0.4, 0.2, vivo.barrios);
const difU = Math.max(...U.map((u, i) => Math.abs(u - hexes[i].u)));
const r = solveCorridor(hexes, 3, 0.4, 0.4, 0.2, vivo.barrios);
const fallas: string[] = [];
if (difU > 1e-3) fallas.push(`urgencia difiere hasta ${difU}`);
if (JSON.stringify(r.hexes) !== JSON.stringify(ref.hexes)) fallas.push(`hexes ${r.hexes} != ${ref.hexes}`);
if (r.personas_cubiertas !== ref.personas_cubiertas) fallas.push(`personas ${r.personas_cubiertas} != ${ref.personas_cubiertas}`);
if (Math.abs(r.length_km - ref.length_km) > 1e-6) fallas.push(`km ${r.length_km} != ${ref.length_km}`);
if (Math.abs(r.urgencia_cubierta - ref.urgencia_cubierta) > 1e-3) fallas.push("urgencia cubierta difiere");
if (fallas.length) { console.error("FALLA\n" + fallas.join("\n")); process.exit(1); }
console.log(`OK optimizador: ${r.hexes.length} hex, ${r.length_km.toFixed(2)} km, ${r.personas_cubiertas} personas` +
  ` (azar JS ${r.personas_azar}, Python ${ref.personas_azar}), urgencia máx. dif. ${difU.toExponential(1)}`);
const otros = [[6, 0.7, 0.2, 0.1], [10, 0.2, 0.6, 0.2], [1.5, 0, 0, 1]];
for (const [km, a, b, c] of otros) {
  const o = solveCorridor(hexes, km, a, b, c, vivo.barrios);
  console.log(JSON.stringify({ km, a, b, c, n: o.hexes.length, pers: o.personas_cubiertas, u: +o.urgencia_cubierta.toFixed(4), h: o.hexes.slice(0, 3) }));
}
