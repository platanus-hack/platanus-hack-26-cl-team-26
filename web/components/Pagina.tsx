"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ExpressionSpecification, LngLatBoundsLike } from "maplibre-gl";
import { cellToBoundary, cellToLatLng, cellToParent, cellsToDirectedEdge, directedEdgeToBoundary, getResolution, gridDisk, latLngToCell, polygonToCellsExperimental, POLYGON_TO_CELLS_FLAGS } from "h3-js";
import MapaHex, { COLOR_CORREDOR, COLOR_MINI_ISLA, type Capa, type Foco } from "./MapaHex";
import Cifra from "./Cifra";
import FiltroComunas from "./FiltroComunas";
import { formato, useRevela, useVisible } from "./movimiento";
import { historico, useTerreno, type Especie, type Estado, type HexCols, type InfoComunas } from "@/lib/terreno";

type Serie = { meses: string[]; escenas_landsat: number; escenas_sentinel2: number; media_mes: (number | null)[]; lst_fecha_ultima: string };

const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
const esVerano = (ym: string) => [12, 1, 2].includes(Number(ym.slice(5)));
const mesCorto = (ym: string) => { const [a, m] = ym.split("-").map(Number); return `${MESES[m - 1]} ${a}`; };
const sinNulos = (xs: (number | null)[]) => xs.filter((x): x is number => x != null);
const media = (xs: number[]) => (xs.length ? xs.reduce((s, x) => s + x, 0) / xs.length : 0);
const esc = (s: unknown) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));
const est = (i: number) => ({ "--i": i } as React.CSSProperties);


// Min-max con percentiles 2 y 98, como optimizer._norm.
function norm(xs: (number | null)[]) {
  const v = sinNulos(xs).sort((a, b) => a - b);
  if (!v.length) return xs.map(() => null);
  const p = (q: number) => { const i = (v.length - 1) * q, lo = Math.floor(i); return v[lo] + (v[Math.ceil(i)] - v[lo]) * (i - lo); };
  const lo = p(0.02), hi = p(0.98);
  return xs.map((x) => (x == null ? null : hi > lo ? Math.min(1, Math.max(0, (x - lo) / (hi - lo))) : 0));
}

const VERDE = ["#EFE9DA", "#C5CDA6", "#8C9A63", "#4F6E31"];
// Calor de amarillo a naranjo (mostaza a terracota), urgencia en rojos (crema a rojo ladrillo), e islas en oliva:
// tonos algo terrosos para que convivan con el crema y el oliva de la página.
const ROJO = ["#F6ECDD", "#EDB592", "#D2603F", "#96261C"];
const NARANJO = ["#F6EFD2", "#EBD488", "#DE9A48", "#B95A24"];   // de mostaza a terracota
// Bajo esto una cuadra no es ciudad (igual que MIN_PERSONAS_HEX del optimizador, que tampoco traza por ahí).
const SIN_GENTE = 50;
// Para quién se traza el corredor. Se puede marcar más de una especie: el criterio promedia, con el mismo peso, lo
// que rige a cada una (ecologia.py). La clave junta las elegidas en este orden: humanos, aves, abejas.
const ESPECIES: [Especie, string][] = [["humanos", "Humanos"], ["aves", "Aves"], ["abejas", "Abejas"]];
// Qué mide la escala de color del mapa de Planificar en cada combinación.
const ESCALA: Record<string, string> = {
  humanos: "Urgencia",
  aves: "Dificultad de cruce para las aves",
  abejas: "Dificultad de cruce para las abejas",
  "humanos+aves": "Urgencia y dificultad para las aves",
  "humanos+abejas": "Urgencia y dificultad para las abejas",
  "aves+abejas": "Dificultad de cruce para aves y abejas",
  "humanos+aves+abejas": "Urgencia y dificultad para aves y abejas",
};
const CRITERIO: Record<string, string> = {
  humanos: "Sombra para las personas: va por las cuadras con más calor, menos árboles y más gente.",
  aves: "Eje continuo para las aves: une parques por donde ya hay más copa y menos cemento y pasto abierto.",
  abejas: "Mini islas para las abejas: puntos floridos, una cuadra por medio, que con el mismo presupuesto unen más parques.",
  "humanos+aves": "Personas y aves: un corredor continuo que pesa por igual la urgencia de las personas y lo difícil que es el cruce para un ave.",
  "humanos+abejas": "Personas y abejas: corredor de sombra que pesa por igual urgencia y cemento, con una mini isla florida cada tres cuadras.",
  "aves+abejas": "Aves y abejas: corredor arbolado continuo que evita el cemento, con una mini isla florida cada tres cuadras.",
  "humanos+aves+abejas": "Las tres: urgencia de las personas, copa para las aves y flores para las abejas pesan un tercio cada una; corredor continuo con mini islas.",
};
// Día en que se bajó el extracto de OpenStreetMap (Geofabrik) con parques, servicios y vías.
const OSM_EXTRACTO = "2026-11-21";
// "2026-02-19" → "19 feb 2026"; con hora, en la hora de Santiago.
const fechaDia = (f?: string | null) => { if (!f) return null; const [a, m, d] = f.slice(0, 10).split("-").map(Number); return `${d} ${MESES[m - 1]} ${a}`; };
const fechaHora = (f?: string | null) => {
  if (!f) return null;
  const t = new Date(f);
  if (Number.isNaN(t.getTime())) return null;
  const p = Object.fromEntries(new Intl.DateTimeFormat("es-CL", { timeZone: "America/Santiago", day: "numeric", month: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }).formatToParts(t).map((x) => [x.type, x.value]));
  return `${Number(p.day)} ${MESES[Number(p.month) - 1]} ${p.year}, ${p.hour}:${p.minute} h`;
};
const ISLA = "#4F6E31";   // el oliva del logo
const MORADO = ["#F3ECE6", "#D3BBD6", "#9A6BA8", "#5C2F78"];   // densidad de personas
const AZUL = ["#EEF0EA", "#BBD0CC", "#5E9590", "#1F4F55"];      // especies de aves registradas en el barrio (GBIF)
const AMBAR = ["#F4EFDF", "#EFD58C", "#E3A21A", "#9A5B08"];    // abejas nativas registradas en el barrio (GBIF)
const AVES_MAX = 70;     // especies de aves por barrio desde la que el color ya no sube (percentil 90: 66)
const ABEJAS_MAX = 15;   // registros de abejas nativas por barrio desde los que el color ya no sube
const grad = (c: string[]) => `linear-gradient(90deg,${c.join(",")})`;
const escala = (prop: string, cols: string[], lo: number, hi: number): ExpressionSpecification => {
  const paso = (hi - lo) / (cols.length - 1);
  return ["interpolate", ["linear"], ["coalesce", ["get", prop], lo], ...cols.flatMap((c, i) => [lo + paso * i, c])] as ExpressionSpecification;
};

const CAPAS_AHORA: Capa[] = [
  { id: "calor", color: escala("calor", NARANJO, 0, 1) },
  { id: "copa", color: escala("copa", VERDE, 0, 25) },
  { id: "personas", color: escala("personas", MORADO, 0, 1) },
  { id: "aves", color: escala("av", AZUL, 0, AVES_MAX) },
  { id: "abejas", color: escala("ab", AMBAR, 0, ABEJAS_MAX) },
];
const NOMBRE_CAPA: Record<string, string> = { calor: "Calor", copa: "Árboles", personas: "Personas", aves: "🐦 Aves", abejas: "🐝 Abejas" };
const LEYENDA: Record<string, [string, string]> = {
  calor: [grad(NARANJO), "Índice de calor: temperatura del suelo; donde hay sensores de aire confiables en al menos 5 barrios, 70 % suelo y 30 % aire"],
  copa: [grad(VERDE), "Copa de árboles, de 0 % a 25 % o más"],
  personas: [grad(MORADO), "Personas: 70 % habitantes del Censo en la cuadra y 30 % cercanía a colegios, salud, metro y paraderos"],
  aves: [grad(AZUL), `Especies de aves registradas en el barrio desde 2015, de 0 a ${AVES_MAX} o más (GBIF: eBird, iNaturalist). Registros, no censo: hay más observadores en parques y cerros`],
  abejas: [grad(AMBAR), `Registros de abejas nativas en el barrio desde 2015, de 0 a ${ABEJAS_MAX} o más (GBIF, sobre todo iNaturalist). Sin la abeja de miel ni el abejorro europeo, que son exóticos`],
};
// Cerros isla y parques grandes de Santiago: las islas verdes que el corredor busca unir.
const ISLAS: [string, number, number][] = [
  ["Cerro San Cristóbal", -70.632, -33.422], ["Cerro Renca", -70.713, -33.392], ["Cerro Santa Lucía", -70.6436, -33.4405],
  ["Parque O'Higgins", -70.66, -33.4645], ["Quinta Normal", -70.682, -33.441], ["Cerro Blanco", -70.6445, -33.4195],
];
const HITOS: GeoJSON.FeatureCollection = {
  type: "FeatureCollection",
  features: ISLAS.map(([n, lng, lat]) => ({ type: "Feature", properties: { n }, geometry: { type: "Point", coordinates: [lng, lat] } })),
};
const CAPAS_PLAN: Capa[] = [{ id: "urg", color: ["case", ["get", "k"], ISLA, ["==", ["get", "u"], null], "#E4DFCC", escala("u", ROJO, 0, 0.85)] }];
const CAPAS_HIST: Capa[] = [{ id: "hist", color: ["case", ["==", ["get", "hn"], null], "#E4DFCC", escala("hn", NARANJO, 0, 1)] }];

function encuadreDe(anillos: number[][][], margen = 0.006): LngLatBoundsLike {
  let w = 180, s = 90, e = -180, n = -90;
  for (const a of anillos) for (const [lng, lat] of a) { w = Math.min(w, lng); e = Math.max(e, lng); s = Math.min(s, lat); n = Math.max(n, lat); }
  return [[w - margen, s - margen], [e + margen, n + margen]];
}

// Diferencia contra el promedio de Santiago; en ocre si es peor (más calor o menos copa).
function Dif({ v, base, u, bueno }: { v: number; base: number; u: string; bueno?: boolean }) {
  const d = v - base;
  if (Math.abs(d) < 0.05) return <span className="dif">igual que Santiago</span>;
  const peor = bueno ? d < 0 : d > 0;
  return <span className={`dif${peor ? " peor" : " mejor"}`}>{d > 0 ? "+" : "−"}{formato(Math.abs(d), 1)}{u}</span>;
}

// Presupuesto mínimo para que salga un corredor, redondeado hacia arriba al paso del control (0,5 km); 0 si no hay.
const a0km = (km?: number | null) => (km ? Math.min(20, Math.ceil(km * 2) / 2) : 0);

function Seccion({ id, alt, children }: { id: string; alt?: boolean; children: React.ReactNode }) {
  const ref = useRevela<HTMLElement>();
  return (
    <section ref={ref} id={id} className={`b-sec b-pad revela${alt ? " alt" : ""}`}>
      <div className="b-in">{children}</div>
    </section>
  );
}

type Barrio = { h: string; an: number; asp: number; atop: string; bn: number; bsp: number; btop: string; bx: number };
type Fauna = { consultado: string; barrios: Map<string, Barrio> };
let faunaCache: Promise<Fauna | null> | null = null;
// Aves por barrio y abejas por cuadra, de GBIF (fauna_gbif.py → public/data/fauna.json). Sin el archivo, la capa queda vacía.
function useFauna() {
  const [f, setF] = useState<Fauna | null>(null);
  useEffect(() => {
    faunaCache ??= fetch("/data/fauna.json").then((r) => (r.ok ? r.json() : null)).then((d) => d && {
      consultado: d.consultado, barrios: new Map(d.barrios.map((x: Barrio) => [x.h, x])),
    }).catch(() => null);
    let vivo = true;
    faunaCache.then((d) => vivo && setF(d));
    return () => { vivo = false; };
  }, []);
  return f;
}

export default function Pagina({ serie }: { serie: Serie }) {
  const t = useTerreno();
  // La barra queda fija; al bajar de la portada se le marca el borde para separarla del contenido.
  const [bajo, setBajo] = useState(false);
  useEffect(() => {
    const mira = () => setBajo(window.scrollY > 8);
    mira();
    window.addEventListener("scroll", mira, { passive: true });
    return () => window.removeEventListener("scroll", mira);
  }, []);
  return (
    <main className="b">
      <header className={`b-pad${bajo ? " bajo" : ""}`}><div className="b-in">
        <a className="marca" href="#inicio"><img src="/viridis.svg" alt="" width={34} height={34} />VIRIDIS</a>
        <nav aria-label="Secciones"><a href="#ahora">Datos clave</a><a href="#planificar">Planificar</a><a href="#historico">Histórico</a><a href="/fuentes">Fuentes</a></nav>
      </div></header>

      <section className="b-hero b-pad" id="inicio">
        {/* Sentinel-2 del 6 de febrero de 2026: el oriente verde, el poniente y el sur en gris. Sin texto encima de la foto. */}
        <img className="fondo" src="/img/santiago-s2.webp" srcSet="/img/santiago-s2-1200.webp 1200w, /img/santiago-s2.webp 2400w"
          sizes="100vw" alt="" aria-hidden="true" fetchPriority="high" decoding="async" />
        <div className="velo" aria-hidden="true" />
        <div className="b-in">
          <h1>Donde se necesita <em>el verde</em></h1>
          <p>Los cerros y parques de Santiago son islas donde viven aves y abejas, separadas por calor y cemento. Viridis traza los corredores verdes que las conectan, por donde más falta la sombra. <em>Verde para la fauna y para las personas.</em></p>
          <div className="grupo" style={{ gap: 12 }}>
            <a className="pill llena grande" href="#planificar">Planificar un corredor</a>
            <a className="pill grande" href="#ahora">Ver los datos clave</a>
          </div>
        </div>
      </section>

      {t.info && t.estado ? <Secciones {...t} info={t.info} estado={t.estado} serie={serie} /> : <Esqueletos error={t.error} />}

      {/* Las fuentes y sus notas de método viven en /fuentes; aquí solo queda el enlace. */}
      <footer className="b-pad pie"><div className="b-in">
        <span className="marca"><img src="/viridis.svg" alt="" width={26} height={26} />VIRIDIS</span>
        <a href="/fuentes">Fuentes</a>
      </div></footer>
    </main>
  );
}

const SIN_CORREDOR: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };
// Planificar sin nada elegido: todo el mapa con el velo de lo no elegido, detrás de la invitación.
const TODO_GRIS: Foco = { comunas: [], hexes: [] };

function Esqueletos({ error }: { error: string | null }) {
  return (
    <>
      {[["ahora", "Datos", "clave"], ["planificar", "Planificar", "el corredor"], ["historico", "El calor", "de antes"]].map(([id, titulo, acento], k) => (
        <section key={id} id={id} className={`b-sec b-pad${k % 2 ? "" : " alt"}`} aria-busy={!error}><div className="b-in">
          <h2>{titulo} <em>{acento}</em></h2>
          {error ? (
            <p className="aviso" role="status">No hay conexión con el servidor del mapa. Desde la raíz del repo, córrelo con <code>python -m terreno.servidor --puerto 8000</code> y recarga.</p>
          ) : (
            <div className="sk-bloque" role="status" aria-label="Cargando las 34 comunas del Gran Santiago">
              <div className="sk sk-linea" style={{ width: "38%" }} />
              <div className="sk sk-mapa" />
              <div className="sk-fila"><div className="sk sk-linea" /><div className="sk sk-linea" /><div className="sk sk-linea" /></div>
            </div>
          )}
        </div></section>
      ))}
    </>
  );
}

// Polígonos de las cuadras: los arma h3-js una vez y quedan guardados.
const anillosH3 = new Map<string, number[][]>();
function anillo(h: string) {
  let a = anillosH3.get(h);
  if (!a) { const b = cellToBoundary(h, true); a = [...b, b[0]]; anillosH3.set(h, a); }
  return a;
}

type PropsSecciones = ReturnType<typeof useTerreno> & { info: InfoComunas; estado: Estado; serie: Serie };

// Lo elegido vive en la página: comunas tocadas o una zona dibujada con el lápiz (una cosa o la otra).
// El mapa siempre muestra las 34 comunas (la base) y atenúa lo que no está elegido; al servidor se le manda
// lo elegido para que Planificar trace el corredor ahí. Sin nada elegido, el área son las 34.
function Secciones(props: PropsSecciones) {
  const { info, estado, cambiar } = props;
  const [base, setBase] = useState<HexCols | null>(null);
  const completa = estado.seleccion.length === info.comunas.length && !estado.parametros.zona;
  useEffect(() => { if (completa) setBase(estado.hex); }, [completa, estado.hex]);
  const [elegidas, setElegidas] = useState<string[]>([]);
  const [zona, setZona] = useState<string[] | null>(null);
  const envio = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => {
    clearTimeout(envio.current);
    envio.current = setTimeout(() => cambiar({ comunas: elegidas.length ? elegidas : info.comunas, distritos: [], zona }), 350);
  }, [elegidas, zona]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!base) return <Esqueletos error={props.error} />;
  return <Contenido {...props} B={base} elegidas={elegidas} setElegidas={setElegidas} zona={zona} setZona={setZona} />;
}

function Contenido({ info, estado, cambiar, ocupado, error, serie, B, elegidas, setElegidas, zona, setZona }: PropsSecciones & {
  B: HexCols; elegidas: string[]; setElegidas: React.Dispatch<React.SetStateAction<string[]>>;
  zona: string[] | null; setZona: (z: string[] | null) => void;
}) {
  const H = estado.hex;   // el área que tiene el servidor (lo elegido), para el corredor
  const nada = !elegidas.length && !zona;
  const comIdx = useMemo(() => new Map(info.comunas.map((c, i) => [c, i])), [info]);
  const idxB = useMemo(() => new Map(B.h.map((h, i) => [h, i])), [B.h]);
  const anillos = useMemo(() => B.h.map(anillo), [B.h]);
  const coleccion = (props: (i: number) => Record<string, unknown>): GeoJSON.FeatureCollection => ({
    type: "FeatureCollection",
    features: B.h.map((_, i) => ({ type: "Feature", id: i, properties: { i, c: comIdx.get(B.comuna[i]), cn: B.comuna[i], v: !B.parque[i] && B.pob[i] < SIN_GENTE, ...props(i) }, geometry: { type: "Polygon", coordinates: [anillos[i]] } })),
  });

  // Cuadras elegidas (índices de la base). null = todo Santiago.
  const zonaIdx = useMemo(() => (zona ? zona.flatMap((h) => idxB.get(h) ?? []) : []), [zona, idxB]);
  const marca = useMemo(() => {
    if (zona) return zonaIdx;
    if (!elegidas.length) return null;
    const s = new Set(elegidas);
    return B.comuna.flatMap((c, i) => (s.has(c) ? [i] : []));
  }, [zona, zonaIdx, elegidas, B.comuna]);
  const foco = useMemo<Foco>(() => (zona ? { comunas: [], hexes: zonaIdx } : elegidas.length ? { comunas: elegidas.map((c) => comIdx.get(c) ?? -1), hexes: [] } : null),
    [zona, zonaIdx, elegidas, comIdx]);
  const encuadreArea = useMemo(() => {
    if (zona && zonaIdx.length) return encuadreDe(zonaIdx.map((i) => anillos[i]), 0.012);
    const geo = elegidas.flatMap((c) => info.geo[c] ?? []).flatMap((poly) => poly.map((a) => a.map(([la, lo]) => [lo, la])));
    return encuadreDe(geo.length ? geo : anillos, geo.length ? 0.025 : 0.004);
  }, [zona, zonaIdx, elegidas, anillos, info]);

  const comunasGeo = useMemo<GeoJSON.FeatureCollection>(() => ({
    type: "FeatureCollection",
    features: info.comunas.map((c) => ({
      type: "Feature",
      properties: { c, est: elegidas.includes(c) ? "sel" : "otra" },
      geometry: { type: "MultiPolygon", coordinates: info.geo[c].map((poly) => poly.map((a) => a.map(([la, lo]) => [lo, la]))) },
    })),
  }), [info, elegidas]);
  // Sectores: el borde compartido entre dos cuadras vecinas de la misma comuna y distinto distrito.
  const distritosGeo = useMemo<GeoJSON.FeatureCollection>(() => {
    const lineas: number[][][] = [];
    B.h.forEach((h, i) => {
      for (const n of gridDisk(h, 1)) {
        const j = idxB.get(n);
        if (j == null || j <= i || B.comuna[j] !== B.comuna[i] || B.distrito[j] === B.distrito[i]) continue;
        lineas.push(directedEdgeToBoundary(cellsToDirectedEdge(h, n), true));
      }
    });
    return { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: { type: "MultiLineString", coordinates: lineas } }] };
  }, [B.h, idxB]); // eslint-disable-line react-hooks/exhaustive-deps

  // Tocar una comuna la suma y tocarla otra vez la quita. Una zona dibujada se reemplaza por las comunas.
  function tocarComuna(c: string) {
    setZona(null);
    setElegidas((ant) => (ant.includes(c) ? ant.filter((x) => x !== c) : [...ant, c]));
  }
  function sumar(cs: string[]) { setZona(null); setElegidas((ant) => [...new Set([...ant, ...cs])]); }
  function reiniciar() { setZona(null); setElegidas([]); setPlanTodo(false); }
  // Lápiz: las cuadras pintadas con el pincel más las que quedan dentro del contorno cerrado; cada trazo se suma a la zona anterior.
  function lazo(contorno: [number, number][] | null, pintadas: number[] = []) {
    const res = getResolution(B.h[0]);
    let celdas = pintadas.map((i) => B.h[i]).filter(Boolean);
    if (contorno) celdas = celdas.concat(polygonToCellsExperimental(contorno.map(([lng, lat]) => [lat, lng]), res, POLYGON_TO_CELLS_FLAGS.containmentOverlapping).filter((h) => idxB.has(h)));
    if (!celdas.length && contorno) {
      const [lng, lat] = contorno.reduce(([a, b], [x, y]) => [a + x / contorno.length, b + y / contorno.length], [0, 0]);
      celdas = [latLngToCell(lat, lng, res)].filter((h) => idxB.has(h));
    }
    if (!celdas.length) return;
    setElegidas([]);
    setZona([...new Set([...(zona ?? []), ...celdas])]);
  }

  // Suelo medio por comuna para la lista del cajón.
  const sueloComuna = useMemo(() => {
    const por: Record<string, number[]> = {};
    B.comuna.forEach((c, i) => { if (B.lst[i] != null) (por[c] ??= []).push(B.lst[i] as number); });
    return new Map(Object.entries(por).map(([c, v]) => [c, media(v)]));
  }, [B]);

  // Globo de un clic: los datos de la cuadra y cómo elegir su comuna.
  const datoHex = (i: number): string => {
    const c = B.comuna[i], fila = (n: string, v: string) => `<tr><th scope="row">${n}</th><td>${v}</td></tr>`;
    return `<div class="pop dato"><b>${esc(B.distrito[i])}</b>${B.parque[i] ? " · parque" : ""}
      <table>${fila("Suelo", B.lst[i] == null ? "sin dato" : `${formato(B.lst[i] as number, 1)} °C`)}
      ${B.vivo[i] != null ? fila("Aire, máxima de ayer", `${formato(B.vivo[i] as number, 1)} °C`) : ""}
      ${fila("Copa de árboles", B.copa[i] == null ? "sin dato" : `${formato(B.copa[i] as number, 1)} %`)}
      ${fila("Personas", formato(B.pob[i]))}
      ${faunaDe[i]?.an ? fila("🐦 Aves en el barrio", `${faunaDe[i]!.asp} especies`) : ""}
      ${faunaDe[i]?.bn ? fila("🐝 Abejas nativas en el barrio", `${faunaDe[i]!.bn} ${faunaDe[i]!.bn === 1 ? "registro" : "registros"}`) : ""}
      ${fila("Coordenadas", cellToLatLng(B.h[i]).map((x) => x.toFixed(5)).join(", "))}</table>
      <small>Doble clic para ${elegidas.includes(c) ? "quitar" : "elegir"} ${esc(c)}.</small></div>`;
  };
  const mapaComun = { comunas: comunasGeo, distritos: distritosGeo, datoHex, alComuna: tocarComuna, alLazo: lazo, foco };

  const filtro = <FiltroComunas info={info} elegidas={elegidas} zona={zonaIdx.length} alternar={tocarComuna} sumar={sumar} reiniciar={reiniciar}
    sueloComuna={sueloComuna} ocupado={ocupado} error={error} />;
  // Los mapas de Datos clave y Planificar van sin el panel de arriba a la derecha: queda solo el botón para volver.
  const filtroSolo = <FiltroComunas info={info} elegidas={elegidas} zona={zonaIdx.length} alternar={tocarComuna} sumar={sumar} reiniciar={reiniciar}
    sueloComuna={sueloComuna} ocupado={ocupado} error={error} sinResumen />;

  // ---- Datos clave: calor, árboles y personas (sobre las 34 comunas: la escala de color no cambia al elegir)
  const [capa, setCapa] = useState("calor");
  const [pasada, setPasada] = useState<number | null>(null);
  const calor = useMemo(() => {
    // Igual que optimizer.urgencia: el aire en vivo no reemplaza al suelo, se combina (30 %) y en escala fija de
    // ±3 °C alrededor de la mediana, solo si hay al menos 5 barrios medidos.
    const suelo = norm(B.lst);
    const barrios = new Map<string, number>();
    B.vivo.forEach((v, i) => { if (v != null) barrios.set(cellToParent(B.h[i], 7), v); });
    const vals = [...barrios.values()].sort((a, b) => a - b);
    const mediana = vals.length ? (vals[(vals.length - 1) >> 1] + vals[vals.length >> 1]) / 2 : 0;
    const usar = barrios.size >= 5;
    return suelo.map((s, i) => {
      const v = B.vivo[i];
      if (s == null) return null;
      return usar && v != null ? 0.7 * s + 0.3 * Math.min(1, Math.max(0, 0.5 + (v - mediana) / 6)) : s;
    });
  }, [B]);
  const personas = useMemo(() => {
    const p = norm(B.pob);
    return p.map((x, i) => 0.7 * (x ?? 0.5) + 0.3 * Math.min(1, Math.max(0, B.social[i] ?? 0.5)));   // igual que optimizer.urgencia
  }, [B]);
  const fauna = useFauna();
  const faunaDe = useMemo(() => B.h.map((h) => fauna?.barrios.get(cellToParent(h, 7))), [B.h, fauna]);
  // Texto de la ficha según la capa: en el barrio, porque las ubicaciones no alcanzan para una cuadra.
  const faunaTexto = (i: number) => {
    if (!fauna) return "";
    const f = faunaDe[i];
    if (capa === "aves") return f?.an ? ` 🐦 En el barrio: ${f.asp} especies de aves (${formato(f.an)} registros); las más vistas: ${f.atop}.` : " Sin aves registradas en el barrio (no significa que no haya).";
    if (capa === "abejas") return f?.bn || f?.bx
      ? ` 🐝 En el barrio: ${f.bn} ${f.bn === 1 ? "registro" : "registros"} de abejas nativas${f.btop ? ` (${f.btop})` : ""}${f.bx ? `; además ${f.bx} de abejas exóticas` : ""}.`
      : " Sin abejas registradas en el barrio (no significa que no haya).";
    return "";
  };
  const datosAhora = useMemo(() => coleccion((i) => ({ calor: calor[i], copa: B.copa[i], personas: personas[i], av: faunaDe[i]?.asp ?? 0, ab: faunaDe[i]?.bn ?? 0 })), [calor, personas, anillos, faunaDe]); // eslint-disable-line react-hooks/exhaustive-deps
  // Cifras de lo elegido: el total y, debajo, cada comuna (o cada comuna que toca la zona dibujada).
  const cifras = (idx: number[]) => {
    const l = sinNulos(idx.map((i) => B.lst[i])), cp = sinNulos(idx.map((i) => B.copa[i]));
    return { cuadras: idx.length, suelo: media(l), copa: media(cp), personas: idx.reduce((s, i) => s + B.pob[i], 0) };
  };
  const santiago = useMemo(() => cifras(B.h.map((_, i) => i)), [B]); // eslint-disable-line react-hooks/exhaustive-deps
  const elegido = useMemo(() => {
    if (!marca) return null;
    const por = new Map<string, number[]>();
    for (const i of marca) { const c = B.comuna[i]; if (!por.has(c)) por.set(c, []); por.get(c)!.push(i); }
    return { total: cifras(marca), filas: [...por].map(([c, idx]) => ({ c, ...cifras(idx) })).sort((a, b) => b.suelo - a.suelo) };
  }, [marca, B]); // eslint-disable-line react-hooks/exhaustive-deps
  const conAire = sinNulos((marca ?? B.h.map((_, i) => i)).map((i) => B.vivo[i]));
  const det = pasada;

  // ---- Planificar: presupuesto y pesos van al servidor, que recalcula el corredor
  const p = estado.parametros;
  // Calor, árboles y personas suman 100. El peso de biodiversidad de terreno queda en 0.
  const [pesos, setPesos] = useState(() => {
    const tot = p.w_calor + p.w_arbol + p.w_personas || 1;
    return { km: p.km, calor: Math.round((100 * p.w_calor) / tot), arbol: Math.round((100 * p.w_arbol) / tot),
             pers: Math.round((100 * p.w_personas) / tot), bio: 0 };
  });
  const temporizador = useRef<ReturnType<typeof setTimeout>>(undefined);
  function mover(k: keyof typeof pesos, v: number) {
    const nuevo = { ...pesos, [k]: v };
    setPesos(nuevo);
    clearTimeout(temporizador.current);
    temporizador.current = setTimeout(() => {
      const w = nuevo.calor + nuevo.arbol + nuevo.pers + nuevo.bio > 0 ? nuevo : { ...nuevo, calor: 40, arbol: 40, pers: 20, bio: 0 };
      cambiar({ km: w.km, w_calor: w.calor, w_arbol: w.arbol, w_personas: w.pers, w_bio: w.bio });
    }, 450);
  }
  const total = pesos.calor + pesos.arbol + pesos.pers + pesos.bio || 1;
  const a = estado.ahora, b = estado.antes;
  // La urgencia es relativa al área del servidor: fuera de lo elegido las cuadras quedan sin valor (gris tenue).
  const datosPlan = useMemo(() => {
    const u = new Map(H.h.map((h, j) => [h, H.u[j]]));
    return coleccion((i) => ({ u: u.get(B.h[i]) ?? null, k: B.parque[i] }));
  }, [H, anillos]); // eslint-disable-line react-hooks/exhaustive-deps
  const anillosH = useMemo(() => H.h.map(anillo), [H.h]);
  // El corredor solo se rearma si cambian sus cuadras (no cada vez que llega un estado nuevo del servidor).
  // Con «comunas vecinas» el corredor puede salir de lo elegido: esas cuadras llegan aparte (estado.fuera).
  const fuera = estado.fuera ?? [];
  const firmaCorredor = H.h.map((h, i) => (H.ahora[i] || H.checkpoint?.[i] || H.antes[i] || H.verificado[i] ? `${h}${+H.ahora[i]}${+!!H.checkpoint?.[i]}${+H.antes[i]}${+H.verificado[i]}` : "")).join("") + fuera.map((f) => f.h + (f.isla ? "i" : "")).join();
  const corredor = useMemo<GeoJSON.FeatureCollection>(() => ({
    type: "FeatureCollection",
    features: H.h.flatMap((h, i) => [
      ...(H.ahora[i] ? ["ahora"] : []),
      ...(H.checkpoint?.[i] ? ["checkpoint"] : []),
    ].map((tipo) => ({ type: "Feature" as const, properties: { tipo, h3: h, comuna: H.comuna[i] }, geometry: { type: "Polygon" as const, coordinates: [anillosH[i]] } })))
      .concat(fuera.flatMap((f) => ["ahora", ...(f.isla ? ["checkpoint"] : [])].map((tipo) => ({ type: "Feature" as const, properties: { tipo, h3: f.h, comuna: f.comuna ?? "" }, geometry: { type: "Polygon" as const, coordinates: [anillo(f.h)] } })))),
  }), [firmaCorredor, anillosH]); // eslint-disable-line react-hooks/exhaustive-deps
  const enCorredor = H.h.flatMap((_, i) => (H.ahora[i] ? [i] : []));
  // Aves y abejas registradas (GBIF) en los barrios que cruza el corredor.
  const faunaCorredor = useMemo(() => {
    const bs = [...new Set(enCorredor.map((i) => cellToParent(H.h[i], 7)))].flatMap((b) => fauna?.barrios.get(b) ?? []);
    if (!bs.length) return null;
    const rico = bs.reduce((x, y) => (y.asp > x.asp ? y : x));
    return { barrios: new Set(enCorredor.map((i) => cellToParent(H.h[i], 7))).size, aves: rico.asp, top: rico.atop.split("; ").slice(0, 3).join(", "),
      abejas: bs.reduce((t, b) => t + b.bn, 0) };
  }, [enCorredor.join(), fauna]); // eslint-disable-line react-hooks/exhaustive-deps
  const comunasFuera = [...new Set(fuera.flatMap((f) => (f.comuna ? [f.comuna] : [])))].sort();
  const comunasCorredor = [...new Set([...enCorredor.map((i) => H.comuna[i]), ...comunasFuera])].sort();
  const claveCorredor = enCorredor.map((i) => H.h[i]).join() + fuera.map((f) => f.h).join();
  const anillosCorredor = () => [...enCorredor.map((i) => anillosH[i]), ...fuera.map((f) => anillo(f.h))];
  // Conectar con parques e islas verdes de las comunas vecinas (no aplica con todo Santiago elegido).
  const especies: Especie[] = p.especies?.length ? p.especies : ["humanos"];
  const claveEspecies = ESPECIES.map(([id]) => id).filter((id) => especies.includes(id)).join("+");
  const soloHumanos = claveEspecies === "humanos";
  // Marcar o desmarcar una especie; siempre queda al menos una.
  function alternarEspecie(id: Especie) {
    const nuevas = especies.includes(id) ? especies.filter((e) => e !== id) : [...especies, id];
    if (nuevas.length) cambiar({ especies: nuevas });
  }
  const vecinasOn = !!p.vecinas;
  const hayVecinas = !nada;
  const kmSugerido = a0km(estado.ahora.km_min);
  // Por defecto se ve el área completa (las 34 comunas si están todas); el corredor se acerca a pedido.
  const [cerca, setCerca] = useState(false);
  // Planificar viene después del filtro: sin nada elegido el mapa invita a elegir (o a usar todo Santiago a propósito).
  const [planTodo, setPlanTodo] = useState(false);
  const planListo = !nada || planTodo;
  // El corredor que se muestra tiene que ser el de lo elegido ahora, no el del área anterior del servidor.
  const esperadas = elegidas.length ? elegidas : info.comunas;
  const alDia = !ocupado && estado.seleccion.length === esperadas.length && esperadas.every((c) => estado.seleccion.includes(c)) && estado.parametros.zona === zonaIdx.length;
  const verCorredor = planListo && alDia;
  useEffect(() => setCerca(false), [encuadreArea]);
  const encuadrePlan = useMemo(() => (cerca && enCorredor.length ? encuadreDe(anillosCorredor(), 0.025) : encuadreArea),
    [cerca, claveCorredor, encuadreArea]); // eslint-disable-line react-hooks/exhaustive-deps

  function exportar() {
    const fc = { type: "FeatureCollection", features: corredor.features.filter((f) => f.properties?.tipo === "ahora") };
    const blob = new Blob([JSON.stringify(fc)], { type: "application/geo+json" });
    const enlace = document.createElement("a");
    enlace.href = URL.createObjectURL(blob);
    enlace.download = `corredor_${formato(a.km, 2).replace(",", "_")}km.geojson`;
    enlace.click();
    URL.revokeObjectURL(enlace.href);
  }

  // ---- Histórico: el servidor promedia las escenas del área entre dos fechas
  const [refHist, verHist] = useVisible<HTMLDivElement>("300px");
  const [desde, setDesde] = useState(12);
  const [hist, setHist] = useState<Map<string, number> | null>(null);
  const [mesesHist, setMesesHist] = useState(0);
  const [errHist, setErrHist] = useState<string | null>(null);
  const hasta = `${serie.meses[serie.meses.length - 1]}-28`;
  useEffect(() => {
    if (!verHist) return;
    let vivo = true;
    historico(`${serie.meses[desde]}-01`, hasta)
      .then((r) => { if (vivo) { setHist(new Map(r.h.flatMap((h, i) => (r.lst[i] == null ? [] : [[h, r.lst[i] as number] as const])))); setMesesHist(r.meses); setErrHist(null); } })
      .catch((e) => vivo && setErrHist(String(e.message)));
    return () => { vivo = false; };
  }, [verHist, desde, estado.sel_id, hasta, serie.meses]);
  const promHex = useMemo(() => B.h.map((h) => hist?.get(h) ?? null), [hist, B.h]);
  const escalaHist = useMemo(() => {
    const v = sinNulos(promHex).sort((x, y) => x - y);
    return v.length ? [v[Math.floor(v.length * 0.02)], v[Math.ceil(v.length * 0.98) - 1]] : [0, 1];
  }, [promHex]);
  const datosHist = useMemo(() => coleccion((i) => ({
    hn: promHex[i] == null ? null : Math.min(1, Math.max(0, ((promHex[i] as number) - escalaHist[0]) / (escalaHist[1] - escalaHist[0] || 1))),
  })), [promHex, escalaHist, anillos]); // eslint-disable-line react-hooks/exhaustive-deps
  const histComuna = useMemo(() => {
    const por: Record<string, number[]> = {};
    (marca ?? B.h.map((_, i) => i)).forEach((i) => { if (promHex[i] != null) (por[B.comuna[i]] ??= []).push(promHex[i] as number); });
    return Object.entries(por).map(([c, v]) => [c, media(v)] as const).sort((x, y) => y[1] - x[1]);
  }, [promHex, B, marca]);
  const promElegido = media(sinNulos((marca ?? B.h.map((_, i) => i)).map((i) => promHex[i])));
  const mm = sinNulos(serie.media_mes);
  const lo = Math.min(...mm), hi = Math.max(...mm);

  return (
    <>
      <Seccion id="ahora" alt>
        <div className="b-cab escalon">
          <div className="titulo">
            <h2>Datos <em>clave</em></h2>
            <small>Haz doble clic en una comuna para fijarla, o encierra cuadras con el lápiz.</small>
          </div>
          <div className="grupo" role="group" aria-label="Capa del mapa">
            {CAPAS_AHORA.map((c) => <button key={c.id} type="button" className="pill" aria-pressed={capa === c.id} onClick={() => setCapa(c.id)}>{NOMBRE_CAPA[c.id]}</button>)}
          </div>
        </div>
        <div className="escalon" style={est(1)}>
          <MapaHex {...mapaComun} datos={datosAhora} capas={CAPAS_AHORA} activa={capa} encuadre={encuadreArea} alPasar={setPasada}
            etiqueta={`Mapa de ${NOMBRE_CAPA[capa].toLowerCase()} por cuadra. Un clic en una cuadra muestra sus datos; doble clic suma o quita su comuna.`}>{filtroSolo}</MapaHex>
        </div>
        <div className="leyenda">
          <span><i className="barra" style={{ background: LEYENDA[capa][0] }} />{LEYENDA[capa][1]}</span>
          <span><i className="linea" style={{ borderTop: "2px solid #2F4520" }} />Comuna</span>
          <span><i className="linea" style={{ borderTop: "2px dashed #2F4520", opacity: 0.7 }} />Sector</span>
          <span><svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true" style={{ verticalAlign: "-2px", marginRight: 6 }}><path d="M12 2l8.66 5v10L12 22l-8.66-5V7z" fill="none" stroke="#2F4520" strokeWidth="2" /></svg>1 hexágono ≈ 0,1 km², unas 4 manzanas</span>
          <span><i className="cuadro" style={{ background: "#B9B5A3", opacity: 0.45 }} />Tenue: casi sin habitantes (cerros, campo, industria)</span>
          {!nada && <span><i className="cuadro" style={{ background: "#C5CDA6", opacity: 0.35 }} />Fuera de lo elegido</span>}
          <span className="detalle num" aria-live="polite">{det != null
            ? `${B.distrito[det]}${B.parque[det] ? ", parque" : ""}: suelo ${formato(B.lst[det] ?? 0, 1)} °C${B.vivo[det] != null ? `, aire ${formato(B.vivo[det] as number, 1)} °C` : ""}, copa ${formato(B.copa[det] ?? 0, 1)} %, ${formato(B.pob[det])} personas.${faunaTexto(det)}`
            : "Un clic en una cuadra muestra sus datos; doble clic elige o quita su comuna."}</span>
        </div>
        <div className="elegido escalon" style={est(3)}>
          {!elegido ? (
            <dl className="fechas">
              <dt>Última actualización de cada dato</dt>
              <dd><b>Calor del suelo</b>{fechaDia(estado.fechas?.calor) ?? "sin fecha"} · Landsat</dd>
              <dd><b>Copa de árboles</b>{fechaDia(estado.fechas?.copa) ?? "sin fecha"} · Sentinel-2</dd>
              <dd><b>Personas</b>Censo 2024 · INE</dd>
              <dd><b>Parques y servicios</b>{fechaDia(OSM_EXTRACTO)} · OpenStreetMap</dd>
              <dd><b>Aire, máxima del día</b>{fechaHora(estado.fechas?.vivo) ?? "sin lecturas confiables"} · DMC y SINCA</dd>
              <dd><b>Aves y abejas</b>{fechaDia(fauna?.consultado) ?? "sin datos"} · GBIF</dd>
            </dl>
          ) : (
            <>
              <div className="totales num">
                <span className="quien">{zona ? "Zona dibujada" : elegidas.length === 1 ? elegidas[0] : `${elegidas.length} comunas`}</span>
                <span><b><Cifra valor={elegido.total.suelo} dec={1} /> °C</b> suelo <Dif v={elegido.total.suelo} base={santiago.suelo} u=" °C" /></span>
                <span><b><Cifra valor={elegido.total.copa} dec={1} /> %</b> copa <Dif v={elegido.total.copa} base={santiago.copa} u=" pts" bueno /></span>
                <span><b><Cifra valor={elegido.total.personas} /></b> personas</span>
                <span><b>{formato(elegido.total.cuadras)}</b> cuadras</span>
              </div>
              {(elegido.filas.length > 1 || zona) && (
                <div className="tabla-env">
                  <table className="tabla-elegido num">
                    <thead><tr><th scope="col">{zona ? "Comunas que toca la zona" : "Comuna"}</th><th scope="col">Suelo</th><th scope="col">Frente a Santiago</th><th scope="col">Copa</th><th scope="col">Personas</th><th scope="col">Cuadras</th>{!zona && <th scope="col"><span className="sr">Quitar</span></th>}</tr></thead>
                    <tbody>
                      {elegido.filas.map((f) => (
                        <tr key={f.c}>
                          <th scope="row">{f.c}</th>
                          <td>{formato(f.suelo, 1)} °C</td>
                          <td><Dif v={f.suelo} base={santiago.suelo} u=" °C" /></td>
                          <td>{formato(f.copa, 1)} %</td>
                          <td>{formato(f.personas)}</td>
                          <td>{formato(f.cuadras)}</td>
                          {!zona && <td><button type="button" className="quita" aria-label={`Quitar ${f.c}`} onClick={() => tocarComuna(f.c)}>×</button></td>}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="nota">Santiago completo: {formato(santiago.suelo, 1)} °C de suelo y {formato(santiago.copa, 1)} % de copa. {conAire.length
                ? `Aire en vivo con confianza alta o media en ${conAire.length.toLocaleString("es-CL")} cuadras de lo elegido: ${formato(media(conAire), 1)} °C de media.`
                : "Sin sensores de aire con confianza alta o media en lo elegido: el calor sale solo del satélite."}</p>
            </>
          )}
        </div>
      </Seccion>

      <Seccion id="planificar">
        <div className="b-cab escalon">
          <h2>Planificar <em>el corredor</em></h2>
          <div className="grupo especies" role="group" aria-label="Para quién se traza el corredor: se puede marcar más de una">
            {ESPECIES.map(([id, label]) => (
              <button key={id} type="button" className="pill" disabled={ocupado} aria-pressed={especies.includes(id)}
                title={especies.length === 1 && especies[0] === id ? "Tiene que quedar al menos una" : undefined}
                onClick={() => alternarEspecie(id)}>
                {label}
              </button>
            ))}
          </div>
          <p className="criterio" aria-live="polite">{CRITERIO[claveEspecies]}</p>
        </div>
        <div className={`b-controles escalon${planListo ? "" : " espera"}`} style={est(2)}>
          {([["calor", "Calor (suelo y aire)"], ["arbol", "Falta de árboles"], ["pers", "Personas cerca"]] as const).map(([k, nombre]) => (
            <div className="peso" key={k}>
              <label htmlFor={`p-${k}`}><span>{nombre}</span><b>{Math.round((100 * pesos[k]) / total)} %</b></label>
              <input id={`p-${k}`} type="range" min={0} max={100} step={5} value={pesos[k]} onChange={(e) => mover(k, Number(e.target.value))} />
            </div>
          ))}
          <div className="peso">
            <label htmlFor="p-km"><span>Presupuesto</span><b>{formato(pesos.km, pesos.km % 1 ? 1 : 0)} km</b></label>
            <input id="p-km" type="range" min={1} max={20} step={0.5} value={pesos.km} onChange={(e) => mover("km", Number(e.target.value))} />
          </div>
          <label className={`vecinas${hayVecinas ? "" : " no"}`}>
            <input type="checkbox" checked={vecinasOn && hayVecinas} disabled={!hayVecinas || ocupado} onChange={(e) => cambiar({ vecinas: e.target.checked })} />
            <span><b>Conectar con islas y parques de comunas vecinas</b><small>{hayVecinas
              ? "El corredor puede partir o llegar a parques e islas verdes de las comunas de al lado, para cualquier combinación de especies. Al menos la mitad de cada tramo va por lo elegido."
              : "Elige una comuna o una zona para usarlo: con todo Santiago ya se usan todos los parques."}</small></span>
          </label>
        </div>
        <div className="b-plan">
          <div className="izq escalon" style={est(3)}>
            <MapaHex {...mapaComun} foco={planListo ? foco : TODO_GRIS} hitos={HITOS} datos={datosPlan} capas={CAPAS_PLAN} activa="urg" corredor={verCorredor ? corredor : SIN_CORREDOR} encuadre={encuadrePlan}
              etiqueta="Corredor propuesto sobre la urgencia de cada cuadra">
              {filtroSolo}
              {!planListo && <div className="gris" aria-hidden="true" />}
              {!planListo && (
                <div className="invita" role="status">
                  <b>Primero elige dónde</b>
                  <span>Haz doble clic en comunas de este mapa o encierra cuadras con el lápiz. El corredor se traza solo dentro de lo que elijas.</span>
                  <button type="button" className="mini" onClick={() => setPlanTodo(true)}>Trazar en todo Santiago</button>
                </div>
              )}
            </MapaHex>
            {verCorredor && enCorredor.length > 0 && (
              <button type="button" className="pill zoom-corredor" aria-pressed={cerca} onClick={() => setCerca(!cerca)}>
                {cerca ? (nada ? "Ver las 34 comunas" : "Ver toda el área") : "Acercar al corredor"}
              </button>
            )}
            <div className="leyenda">
              {/* Solo lo que el mapa dibuja en este momento, según las especies y si hay corredor. */}
              {planListo && <span><i className="barra" style={{ background: grad(ROJO) }} />{ESCALA[claveEspecies]}</span>}
              {verCorredor && a.hexes > 0 && <span><i className="cuadro" style={{ background: COLOR_CORREDOR, outline: "2px solid #2F4520", outlineOffset: -1 }} />{claveEspecies === "abejas" ? "Ruta entre mini islas" : "Corredor"}</span>}
              {verCorredor && (a.checkpoints ?? 0) > 0 && <span><i className="cuadro" style={{ background: COLOR_MINI_ISLA, outline: "2px solid #7A5B00", outlineOffset: -1 }} />Mini isla para abejas</span>}
              <span><i className="cuadro" style={{ background: ISLA }} />Islas verdes: cerros y parques</span>
            </div>
          </div>
          {!planListo ? (
            <div className="cifras pasos">
              <b>Cómo se planifica</b>
              <ol>
                <li><b>Elige dónde.</b> Una o varias comunas, o una zona dibujada con el lápiz.</li>
                <li><b>Ajusta los pesos</b> de calor, falta de árboles y personas, y el presupuesto en kilómetros.</li>
                <li><b>Revisa el corredor</b> que aparece en el mapa y expórtalo.</li>
              </ol>
            </div>
          ) : !alDia ? (
            <div className="cifras" role="status" aria-label="Trazando el corredor">
              <span className="nota">Trazando el corredor en {zona ? "la zona dibujada" : nada ? "todo Santiago" : elegidas.length === 1 ? elegidas[0] : `${elegidas.length} comunas`}…</span>
              <div className="sk" style={{ height: 64, width: "70%" }} /><div className="sk sk-linea" /><div className="sk" style={{ height: 64, width: "55%" }} /><div className="sk sk-linea" /><div className="sk" style={{ height: 120 }} />
            </div>
          ) : (
          <div className="cifras">
            {a.hexes ? (
              <>
                <div className="cifra escalon" style={est(4)}>
                  <b><Cifra valor={a.personas_cubiertas} /></b>
                  <span>personas viven junto al corredor.{soloHumanos && <> Con un trazado al azar del mismo largo serían <strong className="num"><Cifra valor={a.personas_azar} /></strong>.</>}</span>
                </div>
                <div className="cifra escalon" style={est(5)}>
                  <b><Cifra valor={a.km} dec={2} sufijo={" km"} /></b>
                  <span>en {a.hexes} cuadras{comunasCorredor.length ? `, en ${comunasCorredor.join(", ")}` : ""}{fuera.length ? ` (${fuera.length} en comunas vecinas)` : ""}. Urgencia cubierta {formato(a.urgencia_cubierta, 3)}, contra {formato(a.urgencia_azar, 3)} al azar.</span>
                </div>
                {(a.checkpoints ?? 0) > 0 && (
                  <div className="cifra escalon" style={est(5)}>
                    <b><Cifra valor={a.checkpoints ?? 0} /></b>
                    <span>mini islas floridas para abejas{claveEspecies === "abejas" ? `, que conectan ${a.parques_conectados ?? 0} parques` : " sobre el corredor"}.</span>
                  </div>
                )}
              </>
            ) : (
              <div className="aviso sin-corredor">
                <b>Sin corredor con {formato(pesos.km, pesos.km % 1 ? 1 : 0)} km.</b>
                {kmSugerido
                  ? <span>El tramo más corto entre dos parques{vecinasOn ? ", contando los de las comunas vecinas," : ""} mide {formato(estado.ahora.km_min ?? 0, 1)} km.</span>
                  : <span>{vecinasOn ? "Ni lo elegido ni sus comunas vecinas tienen dos parques que se puedan unir pasando por aquí. Suma otra comuna." : "Lo elegido no tiene dos parques o islas verdes que unir."}</span>}
                <span className="grupo" style={{ gap: 8 }}>
                  {!vecinasOn && hayVecinas && <button type="button" className="mini" onClick={() => cambiar({ vecinas: true })}>Conectar con comunas vecinas</button>}
                  {kmSugerido > 0 && <button type="button" className="mini" onClick={() => mover("km", kmSugerido)}>Subir el presupuesto a {formato(kmSugerido, kmSugerido % 1 ? 1 : 0)} km</button>}
                </span>
              </div>
            )}
            <div className="grupo escalon" style={est(6)}>
              <button type="button" className="pill llena" onClick={exportar} disabled={!a.hexes}>Exportar tramos</button>
            </div>
            {faunaCorredor && (
              <div className="cifra escalon" style={est(7)}>
                <b><Cifra valor={faunaCorredor.aves} /></b>
                <span>especies de aves registradas {faunaCorredor.barrios === 1 ? "en el barrio que cruza el corredor" : `en el barrio más rico de los ${faunaCorredor.barrios} que cruza el corredor`}, entre ellas {faunaCorredor.top}.{faunaCorredor.abejas ? ` Además, ${formato(faunaCorredor.abejas)} ${faunaCorredor.abejas === 1 ? "registro" : "registros"} de abejas nativas en esos barrios.` : ""} Fuente: GBIF.</span>
              </div>
            )}
          </div>
          )}
        </div>
      </Seccion>

      <Seccion id="historico" alt>
        <div className="b-cab escalon"><h2>El calor <em>de antes</em></h2><p>Elige desde qué mes promediar el calor del suelo del área: {serie.escenas_landsat} escenas Landsat, de enero de 2023 a noviembre de 2026.</p></div>
        <div ref={refHist} className="escalon" style={{ ...est(1), display: "flex", flexDirection: "column", gap: 10 }}>
          <div className="b-meses" role="group" aria-label="Mes desde el que se promedia">
            {serie.meses.map((m, j) => {
              const v = serie.media_mes[j];
              const alto = v == null ? 8 : 14 + (86 * (v - lo)) / (hi - lo || 1);
              return (
                <button key={m} type="button" aria-pressed={j === desde} onClick={() => setDesde(j)}
                  aria-label={`${mesCorto(m)}${v != null ? `, suelo medio ${formato(v, 1)} °C` : ", sin escena Landsat"}`}
                  title={`${mesCorto(m)}${v != null ? ` · ${formato(v, 1)} °C` : " · sin escena"}`}>
                  <span style={{ height: `${alto}%`, background: j < desde ? "#D6D9BF" : esVerano(m) ? "#4F6E31" : "#8C9A63", outline: j === desde ? "2px solid #22281A" : undefined, outlineOffset: 1 }} />
                </button>
              );
            })}
          </div>
          <div className="b-ejes num"><span>ene 2023</span><span>ene 2024</span><span>ene 2025</span><span>ene 2026</span><span>nov 2026</span></div>
        </div>
        <div className="b-hist">
          <div className="izq escalon" style={est(2)}>
            <MapaHex {...mapaComun} datos={datosHist} capas={CAPAS_HIST} activa="hist" encuadre={encuadreArea} etiqueta="Promedio del calor del suelo por cuadra en el rango elegido">{filtro}</MapaHex>
            <div className="leyenda" style={{ marginTop: 10 }}><span><i className="barra" style={{ background: grad(NARANJO) }} />{hist ? <span className="num">Suelo medio de {formato(escalaHist[0], 1)} °C a {formato(escalaHist[1], 1)} °C</span> : <span className="sk sk-linea" style={{ display: "inline-block", width: 190, height: 14 }} aria-label="Calculando el promedio" />}</span></div>
          </div>
          <div className="cifras">
            <p style={{ margin: 0, fontSize: 16, color: "var(--oliva-osc)" }}>Rango elegido: <b>{mesCorto(serie.meses[desde])} a nov 2026</b>, {mesesHist} meses con escenas. Las barras altas son los veranos, que son los que usa el índice de calor.</p>
            {errHist && <p className="aviso" role="alert">{errHist}</p>}
            <div className="cifra escalon" style={est(3)}>
              <b>{hist ? <Cifra valor={promElegido} dec={1} sufijo={" °C"} duracion={700} /> : "…"}</b>
              <span>suelo medio del área en el rango.</span>
            </div>
            {histComuna.length > 1 && (
              <p className="nota" style={{ fontSize: 15 }}>Más calientes en el rango: {histComuna.slice(0, 3).map(([c, v]) => `${c} (${formato(v, 1)} °C)`).join(", ")}. Más fresca: {histComuna[histComuna.length - 1][0]} ({formato(histComuna[histComuna.length - 1][1], 1)} °C).</p>
            )}
          </div>
        </div>
      </Seccion>
    </>
  );
}
