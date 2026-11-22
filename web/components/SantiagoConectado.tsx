"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import type { LngLatBoundsLike } from "maplibre-gl";
import { cellToBoundary } from "h3-js";
import MapaHex, { COLOR_CORREDOR, COLOR_MINI_ISLA, type Capa } from "./MapaHex";
import Cifra from "./Cifra";
import { formato, menosMovimiento } from "./movimiento";

// La red completa sobre todo Santiago, de 0 a 100 km, ya calculada por red_conectada.py (public/data/red.json).
// Cada presupuesto son los primeros tramos de la red más larga: la red crece sin cambiar de lugar.
type Paso = {
  km: number; largo_km: number; hexes: string[]; mini: string[]; islas: number; nombres: string[]; personas: number;
  barrios_aves: number; aves_max: number; abejas: number; arboles: number; habitat_ha: number; habitat_islas: number; verde_300m: number;
};
type Red = {
  km_max: number; paso_km: number; metros_por_arbol: number; islas_total: number; personas_total: number; verde_300m_hoy: number;
  red: Record<string, Paso[]>;
};
const pct = (x: number, de: number) => `${formato((100 * x) / de, 0)} %`;

// Por qué conectar la fauna nos sirve a todos: un ciclo de cuatro pasos que vuelve a empezar.
const CICLO: [string, string][] = [
  ["Las islas se tocan", "Aves y abejas ya no quedan atrapadas en un cerro o un parque: pueden ir y volver entre ellos."],
  ["La vida se queda", "Con más espacio y más comida en el camino, más especies encuentran dónde vivir y criar."],
  ["Ellas plantan por nosotros", "Las abejas polinizan árboles, huertos y jardines; las aves llevan semillas de un parque a otro."],
  ["Más verde para todos", "Ese verde da sombra y frescor a quienes viven cerca, y vuelve a abrir camino a la fauna."],
];

const PARA: [string, string, string][] = [
  ["humanos", "Personas", "Sombra donde más calor hace y más gente vive."],
  ["aves", "Aves", "Copa continua de árbol en árbol, lejos del cemento y del pasto abierto."],
  ["abejas", "Abejas", "Mini islas floridas, una cuadra por medio, para saltar de parque en parque."],
  ["todas", "Las tres", "Un solo corredor que pesa por igual a personas, aves y abejas, con mini islas floridas."],
];
const CAPAS: Capa[] = [{ id: "red", color: ["case", ["get", "k"], "#4F6E31", ["get", "v"], "#E4DFCC", "#ECE6D6"] }];
const VACIO: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

let redCache: Promise<Red | null> | null = null;
function useRed() {
  const [r, setR] = useState<Red | null>(null);
  useEffect(() => {
    redCache ??= fetch("/data/red.json").then((x) => (x.ok ? x.json() : null)).catch(() => null);
    let vivo = true;
    redCache.then((d) => vivo && setR(d));
    return () => { vivo = false; };
  }, []);
  return r;
}

const poligono = (h: string, tipo: string): GeoJSON.Feature => {
  const b = cellToBoundary(h, true);
  return { type: "Feature", properties: { tipo, h3: h }, geometry: { type: "Polygon", coordinates: [[...b, b[0]]] } };
};

export default function SantiagoConectado({ base, comunas, encuadre, hitos }: {
  base: GeoJSON.FeatureCollection; comunas: GeoJSON.FeatureCollection; encuadre: LngLatBoundsLike; hitos: GeoJSON.FeatureCollection;
}) {
  const red = useRed();
  const [para, setPara] = useState("todas");
  const [j, setJ] = useState(0);
  const [andando, setAndando] = useState(false);
  const reloj = useRef<ReturnType<typeof setInterval>>(undefined);
  const pasos = red?.red[para] ?? [];
  const ultimo = Math.max(0, pasos.length - 1);
  const p = pasos[Math.min(j, ultimo)];

  // «Ver crecer»: de 0 a km_max, un paso cada 0,55 s (o de una si se pidió menos movimiento).
  function crecer() {
    clearInterval(reloj.current);
    if (menosMovimiento()) { setJ(ultimo); return; }
    setJ(0);
    setAndando(true);
    reloj.current = setInterval(() => setJ((k) => {
      if (k + 1 >= ultimo) { clearInterval(reloj.current); setAndando(false); return ultimo; }
      return k + 1;
    }), 550);
  }
  useEffect(() => () => clearInterval(reloj.current), []);
  const parar = () => { clearInterval(reloj.current); setAndando(false); };

  const corredor = useMemo<GeoJSON.FeatureCollection>(() => (p ? {
    type: "FeatureCollection",
    features: [...(para === "abejas" ? [] : p.hexes.map((h) => poligono(h, "ahora"))), ...p.mini.map((h) => poligono(h, "checkpoint"))],
  } : VACIO), [p, para]);

  const total = pasos[ultimo];
  return (
    <>
      <div className="b-cab escalon">
        <h2>Santiago <em>conectado</em></h2>
        <p>Qué pasa si Santiago construye la red completa. Mueve los kilómetros y mira cómo se unen sus islas verdes: los cerros y parques donde viven aves y abejas.</p>
      </div>
      <div className="b-controles escalon conectado-ctl">
        <div className="grupo" role="group" aria-label="Para quién se traza la red">
          {PARA.map(([id, nombre]) => (
            <button key={id} type="button" className="pill" aria-pressed={para === id} onClick={() => { parar(); setPara(id); }}>{nombre}</button>
          ))}
        </div>
        <p className="criterio">{PARA.find(([id]) => id === para)?.[2]}</p>
        <div className="peso conectado-km">
          <label htmlFor="red-km"><span>Kilómetros de corredor</span><b>{p ? formato(p.largo_km, 1) : "0"} km</b></label>
          <input id="red-km" type="range" min={0} max={ultimo} step={1} value={Math.min(j, ultimo)} disabled={!red}
            aria-valuetext={p ? `${p.km} kilómetros de presupuesto` : undefined} onChange={(e) => { parar(); setJ(Number(e.target.value)); }} />
          <div className="b-ejes num"><span>0 km</span><span>{red ? red.km_max / 2 : 15} km</span><span>{red?.km_max ?? 30} km</span></div>
        </div>
        <button type="button" className="pill llena" onClick={andando ? parar : crecer} disabled={!red}>{andando ? "Pausar" : "Ver crecer la red"}</button>
      </div>
      <div className="b-plan">
        <div className="izq escalon">
          <MapaHex datos={base} capas={CAPAS} activa="red" comunas={comunas} corredor={corredor} hitos={hitos} encuadre={encuadre}
            etiqueta={`Red de corredores de ${p ? formato(p.largo_km, 1) : 0} km sobre todo Santiago, con las islas verdes en oliva`} />
          <div className="leyenda">
            <span><i className="cuadro" style={{ background: "#4F6E31" }} />Islas verdes: cerros y parques</span>
            {para !== "abejas" && <span><i className="cuadro" style={{ background: COLOR_CORREDOR, outline: "2px solid #2F4520", outlineOffset: -1 }} />Corredor</span>}
            {(para === "abejas" || para === "todas") && <span><i className="cuadro" style={{ background: COLOR_MINI_ISLA, outline: "2px solid #7A5B00", outlineOffset: -1 }} />Mini isla florida</span>}
          </div>
        </div>
        <div className="cifras" aria-live="polite">
          {!red ? <div className="sk" style={{ height: 220 }} /> : p && (
            <>
              <div className="cifra">
                <b><Cifra valor={p.habitat_ha} duracion={600} sufijo=" ha" /></b>
                <span>de hábitat unido: {p.habitat_islas} {p.habitat_islas === 1 ? "isla verde que ya no está sola" : "islas verdes que ya no están solas"}{pasos[0]?.habitat_ha ? ` (hoy, ${formato(pasos[0].habitat_ha)} ha al alcance de una abeja)` : ""}{p.nombres.length ? `, entre ellas ${p.nombres.join(", ")}` : ""}.</span>
              </div>
              <div className="cifra">
                <b><Cifra valor={p.verde_300m} duracion={600} /></b>
                <span>personas con un espacio verde a menos de 300 m, como recomienda la OMS: {pct(p.verde_300m, red.personas_total)} de Santiago, contra {pct(red.verde_300m_hoy, red.personas_total)} hoy{p.verde_300m > red.verde_300m_hoy ? ` (${formato(p.verde_300m - red.verde_300m_hoy)} más)` : ""}.</span>
              </div>
              <div className="cifra">
                <b><Cifra valor={p.barrios_aves} duracion={600} /></b>
                <span>barrios con aves registradas cruza la red{p.aves_max ? `; en el más rico, ${p.aves_max} especies` : ""}.</span>
              </div>
              <div className="cifra">
                <b><Cifra valor={para === "abejas" || para === "todas" ? p.mini.length : p.abejas} duracion={600} /></b>
                <span>{para === "abejas" || para === "todas"
                  ? `mini islas floridas para abejas, en barrios con ${formato(p.abejas)} registros de abejas nativas.`
                  : "registros de abejas nativas en los barrios que cruza."}</span>
              </div>
              <p className="nota">Unos {formato(p.arboles)} árboles, si se planta uno cada {red.metros_por_arbol} m de corredor (supuesto, no medición).
                Islas, personas (Censo 2024) y fauna (GBIF) son datos medidos; los 300 m son una cuadra vecina, como en el indicador de acceso a áreas verdes de la OMS Europa (2016); no estimamos grados de enfriamiento porque no hay un coeficiente publicado que citar.</p>
            </>
          )}
        </div>
      </div>
      {total && (
        <p className="conectado-remate escalon">Con {formato(total.largo_km, 0)} km de corredores, <b>{total.habitat_islas} islas verdes</b> dejan de estar solas y <b>{formato(total.verde_300m - (red?.verde_300m_hoy ?? 0))} personas más</b> tienen el verde a 300 m de su casa.</p>
      )}
      <div className="ciclo escalon">
        <h3>Lo que circula <em>por un corredor</em></h3>
        <ol>
          {CICLO.map(([t, d], i) => <li key={t}><b><span className="num">{i + 1}</span>{t}</b><p>{d}</p></li>)}
        </ol>
        <p className="ciclo-vuelta">Y el ciclo vuelve a empezar: conectar la fauna es plantar una ciudad que se cuida sola.</p>
      </div>
    </>
  );
}
