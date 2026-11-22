"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ExpressionSpecification, GeoJSONSource, LngLatBoundsLike, Map as MapaML, MapMouseEvent, MapTouchEvent, Popup } from "maplibre-gl";
import { menosMovimiento, useVisible } from "./movimiento";

// Mapa base: Carto Positron teñido con la paleta crema y salvia. Encima, en este orden:
// hexágonos (una capa de relleno por vista; al cambiar de vista se cruzan las opacidades),
// contornos de comuna (del servidor de terreno; se tocan para elegir el área), corredor
// (relleno del actual, línea punteada del de sin terreno, magenta donde se verificó en terreno),
// y los recorridos en terreno. Las fotos y escuchas no van como puntos (no escalan): al tocar una cuadra con
// datos de terreno se abre su ficha (popupHex), que el servidor arma con lo más nuevo de esa cuadra.
const ESTILO = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";
const OPACIDAD = 0.82;
const VACIO: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

export type Capa = { id: string; color: ExpressionSpecification };
// Lo elegido: índices de comuna (propiedad c de cada cuadra) o cuadras sueltas (propiedad i). null = todo Santiago.
export type Foco = { comunas: number[]; hexes: number[] } | null;
const TENUE = 0.5, VELO = 0.42;   // lo no elegido: capa más transparente y un velo oscuro encima
// Cuadras casi sin habitantes que no son parque (propiedad v: cerros, campo, aeropuerto, industria): muy tenues,
// para que se lea la mancha urbana real y no el rectángulo con que se recortaron los datos.
const VACIA = 0.2;
const vacia: ExpressionSpecification = ["boolean", ["get", "v"], false];

function tenir(mapa: MapaML) {
  for (const l of mapa.getStyle().layers ?? []) {
    const id = l.id.toLowerCase();
    try {
      if (l.type === "background") mapa.setPaintProperty(l.id, "background-color", "#EFE9DA");
      else if (l.type === "fill" && id.includes("water")) mapa.setPaintProperty(l.id, "fill-color", "#CDD6C2");
      else if (l.type === "fill" && /park|wood|grass|forest/.test(id)) mapa.setPaintProperty(l.id, "fill-color", "#DCE0C4");
      else if (l.type === "fill" && /landcover|landuse/.test(id)) mapa.setPaintProperty(l.id, "fill-color", "#EAE5D3");
      else if ((l.type === "fill" || l.type === "fill-extrusion") && id.includes("building")) mapa.setLayoutProperty(l.id, "visibility", "none");
      else if (l.type === "line" && /road|bridge|tunnel|highway|street/.test(id)) mapa.setPaintProperty(l.id, "line-color", "#FBF8EF");
      else if (l.type === "line" && id.includes("water")) mapa.setPaintProperty(l.id, "line-color", "#CDD6C2");
      else if (l.type === "symbol") {
        if (/poi|housenum|roadname_minor|roadname_sec|watername|aeroway|rail/.test(id)) mapa.setLayoutProperty(l.id, "visibility", "none");
        else mapa.setPaintProperty(l.id, "text-color", "#59623F");
      }
    } catch { /* capa sin esa propiedad */ }
  }
}

// Corredor en verde hoja (más claro que las islas, con borde oliva oscuro) y mini islas de abejas en amarillo.
export const COLOR_CORREDOR = "#62A83C", COLOR_MINI_ISLA = "#F4C430";
const TESELA_Z = 9;   // zoom de tesela único para cuadras, sectores y comunas (calzan entre sí y no se recargan)

export default function MapaHex({ datos, capas, activa, corredor, comunas, distritos, capturas, recorridos, popupCaptura,
  popupHex, datoHex, encuadre, foco = null, hitos, alPasar, alComuna, alLazo, etiqueta, children }: {
  datos: GeoJSON.FeatureCollection;
  capas: Capa[];
  activa: string;
  corredor?: GeoJSON.FeatureCollection;      // polígonos con propiedad tipo: "ahora" | "antes" | "verificado"
  comunas?: GeoJSON.FeatureCollection;       // contornos con propiedades c (nombre) y est: sel | otra
  distritos?: GeoJSON.FeatureCollection;     // líneas entre sectores (distritos censales) de una misma comuna
  capturas?: GeoJSON.FeatureCollection;      // puntos con propiedad color
  recorridos?: GeoJSON.FeatureCollection;
  popupCaptura?: (props: Record<string, unknown>) => string;
  popupHex?: (i: number) => Promise<string> | null;  // ficha de la cuadra; null si no tiene datos de terreno
  encuadre: LngLatBoundsLike;
  foco?: Foco;
  hitos?: GeoJSON.FeatureCollection;         // puntos con propiedad n: nombres de cerros isla y parques
  alPasar?: (i: number | null) => void;      // cuadra bajo el puntero
  datoHex?: (i: number) => string;           // HTML con los datos de una cuadra, para el globo de un clic
  alComuna?: (c: string) => void;            // doble clic en una cuadra o comuna: suma o quita su comuna
  alLazo?: (anillo: [number, number][] | null, pintadas?: number[]) => void;  // contorno cerrado en [lng, lat] (o null) y cuadras pintadas con el pincel
  etiqueta: string;
  children?: React.ReactNode;                 // controles que flotan sobre el mapa
}) {
  const [cont, visible] = useVisible<HTMLDivElement>();
  const nodo = useRef<HTMLDivElement>(null);
  const mapa = useRef<MapaML | null>(null);
  const [listo, setListo] = useState(false);
  // pintado: el mapa ya dibujó comunas y cuadras (hasta entonces, skeleton). actualizando: llegó un área nueva.
  const [pintado, setPintado] = useState(false);
  const [actualizando, setActualizando] = useState(false);
  const [rueda, setRueda] = useState<"tactil" | "apagada" | "activa">("apagada");
  const [falla, setFalla] = useState(false);
  const [lapiz, setLapiz] = useState(false);        // dibujando una zona punto a punto
  const [nPuntos, setNPuntos] = useState(0);
  const [areaKm2, setAreaKm2] = useState(0);
  const accion = useRef({ deshacer: () => {}, listo: () => {} });  // los botones llaman al dibujo en curso
  const pasado = useRef<number | null>(null);
  const sinClicHasta = useRef(0);   // al cerrar la zona el mapa dispara un clic que no debe elegir comuna
  const cb = useRef({ alPasar, alComuna, alLazo, popupCaptura, popupHex, datoHex, activa, datos, lapiz });
  cb.current = { alPasar, alComuna, alLazo, popupCaptura, popupHex, datoHex, activa, datos, lapiz };
  const inicial = useRef({ datos, capas, activa, encuadre, hitos });
  const hayComunas = useRef(false), hayCuadras = useRef(false), claveCorredor = useRef("");

  useEffect(() => {
    if (!visible || !nodo.current) return;
    let vivo = true;
    let m: MapaML | null = null;
    let popup: Popup | null = null;
    import("maplibre-gl").then((ml) => {
      if (!vivo || !nodo.current) return;
      // El worker de MapLibre 6 se sirve desde public/ (lo copia "npm run worker").
      ml.setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");
      const ini = inicial.current;
      // En pantallas táctiles se mueve con dos dedos (un dedo sigue bajando la página). Con mouse se arrastra
      // libre y la rueda acerca solo después de hacer clic en el mapa, para no secuestrar el scroll de la página.
      const tactil = window.matchMedia("(pointer: coarse)").matches;
      setRueda(tactil ? "tactil" : "apagada");
      let nuevo: MapaML;
      try { nuevo = new ml.Map({
        container: nodo.current, style: ESTILO, bounds: ini.encuadre,
        fitBoundsOptions: { padding: 32 }, attributionControl: { compact: true },
        cooperativeGestures: tactil, scrollZoom: false, dragRotate: false, pitchWithRotate: false, touchPitch: false,
        minZoom: 8.5, maxZoom: 16.5, fadeDuration: 0,
        locale: {
          "CooperativeGesturesHandler.WindowsHelpText": "Usa Ctrl + rueda para acercar el mapa",
          "CooperativeGesturesHandler.MacHelpText": "Usa ⌘ + rueda para acercar el mapa",
          "CooperativeGesturesHandler.MobileHelpText": "Usa dos dedos para mover el mapa",
          "NavigationControl.ZoomIn": "Acercar", "NavigationControl.ZoomOut": "Alejar",
        },
      }); } catch { setFalla(true); return; }
      m = nuevo;
      nuevo.addControl(new ml.NavigationControl({ showCompass: false }), "top-right");
      nuevo.touchZoomRotate.disableRotation();
      if (!tactil) {
        const activar = () => { nuevo.scrollZoom.enable(); setRueda("activa"); };
        nuevo.on("mousedown", activar);
        nuevo.getContainer().addEventListener("mouseleave", () => { nuevo.scrollZoom.disable(); setRueda("apagada"); });
      }
      nuevo.on("load", () => {
        tenir(nuevo);
        const fundido = { duration: menosMovimiento() ? 0 : 650 };
        // maxzoom 9: las cuadras se cortan en las mismas pocas teselas para todo zoom. Así al alejar no hay que
        // volver a generarlas (antes quedaba dibujado solo el trozo que estaba a la vista hasta que cargaba el resto).
        nuevo.addSource("hex", { type: "geojson", data: ini.datos, promoteId: "i", maxzoom: TESELA_Z, buffer: 16 });
        for (const c of ini.capas) {
          nuevo.addLayer({
            id: c.id, type: "fill", source: "hex",
            layout: { visibility: c.id === ini.activa ? "visible" : "none" },
            paint: { "fill-color": c.color, "fill-opacity": ["case", vacia, VACIA, OPACIDAD], "fill-opacity-transition": fundido, "fill-antialias": false },
          });
        }
        // Con todo el Gran Santiago a la vista los bordes de 13 mil cuadras solo ensucian y cuestan; aparecen al acercar.
        nuevo.addLayer({
          id: "borde", type: "line", source: "hex", minzoom: 11,
          paint: { "line-color": "#F6F1E4", "line-width": 0.35, "line-opacity": ["interpolate", ["linear"], ["zoom"], 11, 0, 12, 1] },
        });
        // Velo oscuro sobre las cuadras no elegidas; apagado mientras se ve todo Santiago.
        nuevo.addLayer({
          id: "velo", type: "fill", source: "hex", layout: { visibility: "none" },
          paint: { "fill-color": "#22281A", "fill-opacity": 0, "fill-antialias": false },
        });
        nuevo.addSource("elegida", { type: "geojson", data: VACIO });
        nuevo.addLayer({ id: "elegida", type: "line", source: "elegida", paint: { "line-color": "#22281A", "line-width": 2.2 } });
        // Sectores: raya fina punteada entre distritos de una misma comuna, más visible al acercar.
        nuevo.addSource("distritos", { type: "geojson", data: VACIO, maxzoom: TESELA_Z, buffer: 16 });
        nuevo.addLayer({
          id: "distritos", type: "line", source: "distritos",
          paint: {
            "line-color": "#2F4520", "line-dasharray": [2, 1.6],
            "line-width": ["interpolate", ["linear"], ["zoom"], 10, 0.6, 13, 1.3],
            "line-opacity": ["interpolate", ["linear"], ["zoom"], 9.5, 0.3, 12, 0.75],
          },
        });
        // Comunas: halo claro debajo y línea oscura encima, para que el límite se lea sobre cualquier color.
        // El relleno es casi transparente: solo sirve para tocar una comuna donde no hay cuadras.
        nuevo.addSource("comunas", { type: "geojson", data: VACIO, maxzoom: TESELA_Z, buffer: 16 });
        nuevo.addLayer({ id: "comunas-relleno", type: "fill", source: "comunas", paint: { "fill-color": "#4F6E31", "fill-opacity": 0.001 } });
        nuevo.addLayer({
          id: "comunas-halo", type: "line", source: "comunas", layout: { "line-join": "round" },
          paint: { "line-color": "#FFFDF6", "line-opacity": 0.8, "line-width": ["interpolate", ["linear"], ["zoom"], 9, ["match", ["get", "est"], "sel", 6.5, 2.6], 13, ["match", ["get", "est"], "sel", 7.5, 4]] },
        });
        nuevo.addLayer({
          id: "comunas-linea", type: "line", source: "comunas", layout: { "line-join": "round" },
          paint: {
            "line-color": ["match", ["get", "est"], "sel", "#22281A", "#2F4520"],
            "line-width": ["interpolate", ["linear"], ["zoom"], 9, ["match", ["get", "est"], "sel", 3.2, 1.3], 13, ["match", ["get", "est"], "sel", 3.6, 2]],
          },
        });
        nuevo.addSource("corredor", { type: "geojson", data: VACIO });
        nuevo.addLayer({
          id: "corredor", type: "fill", source: "corredor", filter: ["==", ["get", "tipo"], "ahora"],
          paint: { "fill-color": COLOR_CORREDOR, "fill-opacity": 0.92, "fill-opacity-transition": { duration: menosMovimiento() ? 0 : 700 } },
        });
        // Contorno grueso para que el corredor se distinga aun con el área completa a la vista.
        nuevo.addLayer({
          id: "corredor-borde", type: "line", source: "corredor", filter: ["==", ["get", "tipo"], "ahora"],
          paint: { "line-color": "#2F4520", "line-width": ["interpolate", ["linear"], ["zoom"], 9, 3, 13, 1.6] },
        });
        nuevo.addLayer({
          id: "corredor-antes", type: "line", source: "corredor", filter: ["==", ["get", "tipo"], "antes"],
          paint: { "line-color": "#22281A", "line-width": 1.6, "line-dasharray": [2, 2] },
        });
        nuevo.addLayer({
          id: "corredor-verificado", type: "line", source: "corredor", filter: ["==", ["get", "tipo"], "verificado"],
          paint: { "line-color": "#B0398B", "line-width": 3 },
        });
        nuevo.addLayer({
          id: "corredor-checkpoint", type: "fill", source: "corredor", filter: ["==", ["get", "tipo"], "checkpoint"],
          paint: { "fill-color": COLOR_MINI_ISLA, "fill-opacity": 0.96 },
        });
        nuevo.addLayer({
          id: "corredor-checkpoint-borde", type: "line", source: "corredor", filter: ["==", ["get", "tipo"], "checkpoint"],
          paint: { "line-color": "#7A5B00", "line-width": 2 },
        });
        nuevo.addSource("recorridos", { type: "geojson", data: VACIO });
        nuevo.addLayer({ id: "recorridos", type: "line", source: "recorridos", paint: { "line-color": "#6B3FA0", "line-width": 4, "line-opacity": 0.85 } });
        // Nombres de los cerros isla y parques grandes, con la misma fuente de letras del mapa base.
        const letra = (nuevo.getStyle().layers ?? []).flatMap((l) => (l.type === "symbol" && Array.isArray(l.layout?.["text-font"]) ? [l.layout["text-font"] as string[]] : []))[0];
        nuevo.addSource("hitos", { type: "geojson", data: inicial.current.hitos ?? VACIO });
        if (letra) nuevo.addLayer({
          id: "hitos", type: "symbol", source: "hitos",
          layout: { "text-field": ["get", "n"], "text-font": letra, "text-size": ["interpolate", ["linear"], ["zoom"], 9, 11, 13, 14], "text-max-width": 7 },
          paint: { "text-color": "#22301A", "text-halo-color": "#FFFDF6", "text-halo-width": 1.8 },
        });
        // Cuadras que va marcando el pincel mientras se arrastra (estado por cuadra, sin recargar datos).
        nuevo.addLayer({ id: "pincel", type: "fill", source: "hex", paint: { "fill-color": "#2F4520", "fill-opacity": ["case", ["boolean", ["feature-state", "pinta"], false], 0.6, 0] } });
        // Autopistas y avenidas principales (OSM, web/public/data/vias.json): una línea fina sobre las cuadras y su
        // nombre a lo largo. Las autopistas se rotulan desde antes; las avenidas, al acercar.
        nuevo.addSource("vias", { type: "geojson", data: "/data/vias.json" });
        nuevo.addLayer({
          id: "vias-linea", type: "line", source: "vias", minzoom: 9.5, layout: { "line-join": "round", "line-cap": "round" },
          filter: ["any", ["<", ["get", "k"], 2], [">=", ["zoom"], 11]],
          paint: { "line-color": "#FFFDF6", "line-opacity": ["case", ["<", ["get", "k"], 2], 0.75, 0.5],
            "line-width": ["interpolate", ["linear"], ["zoom"], 9.5, ["case", ["<", ["get", "k"], 2], 0.9, 0.4], 14, ["case", ["<", ["get", "k"], 2], 3, 1.8]] },
        }, "distritos");
        // Nombres de las comunas en gris suave: aparecen al acercar (de lejos el mapa base solo dice «Santiago»).
        nuevo.addSource("comunas-nombre", { type: "geojson", data: VACIO });
        if (letra) {
          nuevo.addLayer({
            id: "vias-nombre", type: "symbol", source: "vias", minzoom: 10.3,
            filter: ["any", ["<", ["get", "k"], 2], [">=", ["zoom"], 11.8]],
            layout: { "symbol-placement": "line", "text-field": ["get", "n"], "text-font": letra, "symbol-spacing": 320,
              "text-size": ["interpolate", ["linear"], ["zoom"], 10.3, 10, 14, 13], "text-letter-spacing": 0.03, "text-max-angle": 35 },
            paint: { "text-color": "#3F4730", "text-halo-color": "rgba(255, 253, 246, 0.9)", "text-halo-width": 1.6 },
          });
          nuevo.addLayer({
            id: "comunas-nombre", type: "symbol", source: "comunas-nombre", minzoom: 10.4,
            layout: { "text-field": ["get", "n"], "text-font": letra, "text-transform": "uppercase", "text-letter-spacing": 0.12, "text-max-width": 7,
              "text-size": ["interpolate", ["linear"], ["zoom"], 10.4, 10.5, 13.5, 15], "text-padding": 6 },
            paint: { "text-color": "#6F7266", "text-halo-color": "rgba(246, 241, 228, 0.85)", "text-halo-width": 1.4,
              "text-opacity": ["interpolate", ["linear"], ["zoom"], 10.4, 0, 10.9, 0.95] },
          });
        }
        nuevo.addSource("lazo", { type: "geojson", data: VACIO });
        nuevo.addLayer({ id: "lazo-relleno", type: "fill", source: "lazo", filter: ["==", ["get", "tipo"], "zona"], paint: { "fill-color": "#966222", "fill-opacity": 0.14 } });
        nuevo.addLayer({ id: "lazo", type: "line", source: "lazo", filter: ["==", ["get", "tipo"], "borde"], layout: { "line-join": "round", "line-cap": "round" }, paint: { "line-color": "#22281A", "line-width": 2.4 } });
        nuevo.addLayer({ id: "lazo-guia", type: "line", source: "lazo", filter: ["==", ["get", "tipo"], "guia"], layout: { "line-cap": "round" }, paint: { "line-color": "#22281A", "line-width": 1.6, "line-opacity": 0.7, "line-dasharray": [2, 2] } });
        nuevo.addLayer({ id: "lazo-vertices", type: "circle", source: "lazo", filter: ["==", ["get", "tipo"], "punto"],
          paint: { "circle-radius": ["case", ["get", "cierra"], 8, 6], "circle-color": ["case", ["get", "cierra"], "#F3E3BF", "#FFFDF6"], "circle-stroke-color": "#22281A", "circle-stroke-width": 2 } });
        nuevo.addSource("capturas", { type: "geojson", data: VACIO });
        nuevo.addLayer({
          id: "capturas", type: "circle", source: "capturas",
          paint: { "circle-radius": 7, "circle-color": ["get", "color"], "circle-stroke-color": "#FFFDF6", "circle-stroke-width": 2 },
        });

        // Un clic: captura → su foto; cuadra → un globo con sus datos (y sus fotos y aves si tiene). Doble clic
        // (o doble toque): suma o quita la comuna. El clic espera un momento por si llega el segundo. El mapa no
        // hace zoom con doble clic. Con el lápiz activo no se elige nada.
        nuevo.doubleClickZoom.disable();
        let espera: ReturnType<typeof setTimeout> | null = null;
        let previo = { t: 0, x: 0, y: 0 };
        const unClic = (e: MapMouseEvent) => {
          const cap = nuevo.queryRenderedFeatures(e.point, { layers: ["capturas"] })[0];
          if (cap && cb.current.popupCaptura) {
            popup?.remove();
            popup = new ml.Popup({ maxWidth: "260px" }).setLngLat(e.lngLat).setHTML(cb.current.popupCaptura(cap.properties)).addTo(nuevo);
            return;
          }
          const hex = nuevo.getLayer(cb.current.activa) ? nuevo.queryRenderedFeatures(e.point, { layers: [cb.current.activa] })[0] : undefined;
          if (!hex) { popup?.remove(); return; }
          const dato = cb.current.datoHex?.(Number(hex.id)) ?? "";
          const ficha = cb.current.popupHex?.(Number(hex.id));
          if (!dato && !ficha) return;
          popup?.remove();
          const mio = new ml.Popup({ maxWidth: "300px" }).setLngLat(e.lngLat)
            .setHTML(dato + (ficha ? '<div class="pop">Cargando fotos y aves de esta cuadra…</div>' : "")).addTo(nuevo);
          popup = mio;
          ficha?.then((html) => mio.setHTML(dato + html)).catch(() => mio.setHTML(dato + '<div class="pop">No se pudieron cargar las fotos de la cuadra.</div>'));
        };
        const dobleClic = (e: MapMouseEvent) => {
          popup?.remove();
          const hex = nuevo.getLayer(cb.current.activa) ? nuevo.queryRenderedFeatures(e.point, { layers: [cb.current.activa] })[0] : undefined;
          if (hex?.properties.cn) { cb.current.alComuna?.(String(hex.properties.cn)); return; }
          const com = nuevo.queryRenderedFeatures(e.point, { layers: ["comunas-relleno"] })[0];
          if (com) cb.current.alComuna?.(String(com.properties.c));
        };
        nuevo.on("click", (e) => {
          if (cb.current.lapiz || performance.now() < sinClicHasta.current) return;
          const t = performance.now();
          const doble = t - previo.t < 350 && Math.hypot(e.point.x - previo.x, e.point.y - previo.y) < 30;
          previo = doble ? { t: 0, x: 0, y: 0 } : { t, x: e.point.x, y: e.point.y };
          if (espera) { clearTimeout(espera); espera = null; }
          if (doble) dobleClic(e);
          else espera = setTimeout(() => { espera = null; unClic(e); }, 280);
        });
        // Al pasar el puntero: contorno de la cuadra y sus datos abajo del mapa.
        const pasar = (i: number | null) => {
          if (i === pasado.current) return;
          pasado.current = i;
          const f = i == null ? null : cb.current.datos.features[i];
          (nuevo.getSource("elegida") as GeoJSONSource).setData(f ? { type: "FeatureCollection", features: [f] } : VACIO);
          cb.current.alPasar?.(i);
        };
        nuevo.on("mousemove", (e) => {
          if (cb.current.lapiz) return;
          const capas = ["capturas", "comunas-relleno", cb.current.activa].filter((x) => nuevo.getLayer(x));
          const fs = nuevo.queryRenderedFeatures(e.point, { layers: capas });
          nuevo.getCanvas().style.cursor = fs.length ? "pointer" : "";
          const hex = fs.find((f) => f.layer.id === cb.current.activa);
          pasar(hex ? Number(hex.id) : null);
        });
        nuevo.getCanvas().addEventListener("mouseleave", () => pasar(null));
        setListo(true);
      });
      // Cada vez que el mapa termina de dibujar lo pendiente, se quita el skeleton o el aviso de actualización.
      nuevo.on("idle", () => {
        const com = nuevo.getSource("comunas") as GeoJSONSource | undefined;
        if (!com || !hayComunas.current || !hayCuadras.current) return;
        setPintado(true);
        setActualizando(false);
      });
      mapa.current = nuevo;
    });
    return () => { vivo = false; popup?.remove(); m?.remove(); mapa.current = null; setListo(false); setPintado(false); };
  }, [visible]);

  useEffect(() => {
    const m = mapa.current;
    if (!listo || !m) return;
    for (const c of capas) if (m.getLayer(c.id)) m.setLayoutProperty(c.id, "visibility", c.id === activa ? "visible" : "none");
  }, [activa, capas, listo]);

  useEffect(() => {
    const m = mapa.current;
    if (!listo || !m) return;
    if (pasado.current != null) { (m.getSource("elegida") as GeoJSONSource).setData(VACIO); pasado.current = null; }
    hayCuadras.current = datos.features.length > 0;
    setActualizando(true);
    (m.getSource("hex") as GeoJSONSource).setData(datos);
  }, [datos, listo]);

  // Lo elegido a color pleno; lo demás atenuado, nunca oculto.
  const claveFoco = foco ? `f:${foco.comunas.join()}|${foco.hexes.length}:${foco.hexes.slice(0, 50).join()}` : "";
  useEffect(() => {
    const m = mapa.current;
    if (!listo || !m) return;
    // Los parques (propiedad k, solo en Planificar) nunca se apagan: son las islas verdes que une el corredor.
    const dentro: ExpressionSpecification = ["any", ["boolean", ["get", "k"], false], ["in", ["get", "c"], ["literal", foco?.comunas ?? []]], ["in", ["get", "i"], ["literal", foco?.hexes ?? []]]];
    for (const c of capas) if (m.getLayer(c.id)) m.setPaintProperty(c.id, "fill-opacity", foco ? ["case", vacia, ["case", dentro, VACIA + 0.1, VACIA * 0.6], dentro, 0.95, TENUE] : ["case", vacia, VACIA, OPACIDAD]);
    m.setPaintProperty("velo", "fill-opacity", foco ? ["case", dentro, 0, VELO] : 0);
    m.setLayoutProperty("velo", "visibility", foco ? "visible" : "none");
  }, [claveFoco, capas, listo]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!listo) return;
    (mapa.current?.getSource("distritos") as GeoJSONSource | undefined)?.setData(distritos ?? VACIO);
  }, [distritos, listo]);

  // Dos formas de marcar una zona con el mismo lápiz:
  // · Pincel: arrastrar marca las cuadras por donde pasa. Si el trazo vuelve cerca de donde empezó, la zona se cierra
  //   y se rellenan todas las cuadras de adentro; si no, quedan sumadas solo las cuadras pintadas y se sigue pintando.
  // · Punto a punto, como en Google Maps: cada clic pone un punto unido al anterior con una recta; una guía punteada
  //   sigue al puntero. Se cierra tocando el primer punto, con doble clic, Enter o «Listo». Los puntos se arrastran.
  // Mientras el lápiz está activo el mapa se mueve con la rueda, los botones + y −, o con dos dedos. Esc cancela.
  useEffect(() => {
    const m = mapa.current;
    if (!listo || !m) return;
    const cont = m.getCanvasContainer();
    const src = m.getSource("lazo") as GeoJSONSource;
    if (!lapiz) {
      m.dragPan.enable();
      cont.style.cursor = "";
      setNPuntos(0); setAreaKm2(0);
      return;
    }
    m.dragPan.disable();
    cont.style.cursor = "crosshair";
    const pts: [number, number][] = [];
    // Trazo del pincel en curso: recorrido en [lng, lat], cuadras marcadas y último punto en pantalla.
    let brocha: { trazo: [number, number][]; celdas: Set<number>; ultimo: { x: number; y: number }; largo: number } | null = null;
    const capasHex = () => (m.getStyle().layers ?? []).filter((l) => l.type === "fill" && "source" in l && l.source === "hex" && l.id !== "velo" && l.id !== "pincel").map((l) => l.id);
    const marcar = (x: number, y: number) => {
      if (!brocha) return;
      const capasV = capasHex();
      // Muestras cada ~4 px entre el punto anterior y este, para no saltarse cuadras al arrastrar rápido.
      const { x: x0, y: y0 } = brocha.ultimo, d = Math.hypot(x - x0, y - y0), n = Math.max(1, Math.ceil(d / 4));
      for (let k = 1; k <= n; k++) {
        const px: [number, number] = [x0 + ((x - x0) * k) / n, y0 + ((y - y0) * k) / n];
        for (const f of m.queryRenderedFeatures(px, { layers: capasV })) {
          const i = Number(f.properties?.i);
          if (!Number.isFinite(i) || brocha.celdas.has(i)) continue;
          brocha.celdas.add(i);
          m.setFeatureState({ source: "hex", id: i }, { pinta: true });
        }
      }
      brocha.largo += d; brocha.ultimo = { x, y };
    };
    const limpiarPincel = () => { m.removeFeatureState({ source: "hex" }); };
    let guia: [number, number] | null = null, arrastra = -1, movio = false, soltoEn = 0, cerrada = false;
    const tactil = window.matchMedia("(pointer: coarse)").matches;
    const lejos = (a: [number, number], b: [number, number], px: number) => {
      const p = m.project(a), q = m.project(b);
      return Math.hypot(p.x - q.x, p.y - q.y) > px;
    };
    // Área aproximada (proyección local equirectangular; basta para zonas de unos km).
    const area = () => {
      if (pts.length < 3) return 0;
      const lat0 = (pts.reduce((a, [, la]) => a + la, 0) / pts.length) * Math.PI / 180;
      const xy = pts.map(([lo, la]) => [lo * 111.32 * Math.cos(lat0), la * 110.57]);
      let a = 0;
      for (let k = 0; k < xy.length; k++) { const [x1, y1] = xy[k], [x2, y2] = xy[(k + 1) % xy.length]; a += x1 * y2 - x2 * y1; }
      return Math.abs(a) / 2;
    };
    // El trazo cierra una zona si vuelve a menos de 40 px de donde empezó, tras recorrer bastante más que eso.
    const cierraBrocha = () => !!brocha && brocha.trazo.length >= 3 && brocha.largo > 120 && !lejos(brocha.trazo[0], brocha.trazo[brocha.trazo.length - 1], tactil ? 48 : 40);
    const pintar = () => {
      const fs: GeoJSON.Feature[] = [];
      if (pts.length >= 3) fs.push({ type: "Feature", properties: { tipo: "zona" }, geometry: { type: "Polygon", coordinates: [[...pts, pts[0]]] } });
      if (pts.length >= 2) fs.push({ type: "Feature", properties: { tipo: "borde" }, geometry: { type: "LineString", coordinates: pts } });
      if (brocha && brocha.trazo.length >= 2) {
        fs.push({ type: "Feature", properties: { tipo: "guia" }, geometry: { type: "LineString", coordinates: brocha.trazo } });
        if (cierraBrocha()) fs.push({ type: "Feature", properties: { tipo: "zona" }, geometry: { type: "Polygon", coordinates: [[...brocha.trazo, brocha.trazo[0]]] } });
      }
      if (pts.length && guia && arrastra < 0) {
        const linea = pts.length >= 2 ? [pts[pts.length - 1], guia, pts[0]] : [pts[0], guia];
        fs.push({ type: "Feature", properties: { tipo: "guia" }, geometry: { type: "LineString", coordinates: linea } });
      }
      pts.forEach((pt, j) => fs.push({ type: "Feature", properties: { tipo: "punto", j, cierra: j === 0 && pts.length >= 3 }, geometry: { type: "Point", coordinates: pt } }));
      src.setData({ type: "FeatureCollection", features: fs });
      setNPuntos(pts.length); setAreaKm2(area());
    };
    const cerrar = () => {
      if (pts.length < 3) return;
      sinClicHasta.current = performance.now() + 500;
      cerrada = true; guia = null; pintar();
      cb.current.alLazo?.([...pts]);
      setTimeout(() => src.setData(VACIO), 700);
      setLapiz(false);
    };
    const deshacer = () => { pts.pop(); pintar(); };
    accion.current = { deshacer, listo: cerrar };
    const ll = (e: { lngLat: { lng: number; lat: number } }): [number, number] => [e.lngLat.lng, e.lngLat.lat];
    const clic = (e: MapMouseEvent) => {
      if (performance.now() - soltoEn < 250) return;           // el clic que sigue a arrastrar un punto
      const p = ll(e);
      if (pts.length >= 3 && !lejos(p, pts[0], tactil ? 22 : 12)) { cerrar(); return; }
      if (pts.length && !lejos(p, pts[pts.length - 1], 6)) return;  // segundo clic de un doble clic
      pts.push(p); pintar();
    };
    const mueve = (e: MapMouseEvent) => {
      if (brocha) {
        marcar(e.point.x, e.point.y);
        const p = ll(e);
        if (lejos(p, brocha.trazo[brocha.trazo.length - 1], 3)) brocha.trazo.push(p);
        cont.style.cursor = "crosshair";
        pintar();
        return;
      }
      guia = ll(e);
      if (arrastra >= 0) { pts[arrastra] = guia; movio = true; }
      const sobre = m.queryRenderedFeatures(e.point, { layers: ["lazo-vertices"] }).length > 0;
      cont.style.cursor = arrastra >= 0 ? "grabbing" : sobre ? "grab" : "crosshair";
      if (pts.length) pintar();
    };
    const tomar = (e: MapMouseEvent | MapTouchEvent) => {
      if ("originalEvent" in e && "touches" in e.originalEvent && e.originalEvent.touches.length > 1) {  // dos dedos: mover el mapa
        if (brocha) { brocha = null; limpiarPincel(); pintar(); }
        return;
      }
      if ("button" in e.originalEvent && (e.originalEvent as MouseEvent).button !== 0) return;
      const f = m.queryRenderedFeatures(e.point, { layers: ["lazo-vertices"] })[0];
      e.preventDefault();
      if (f) { arrastra = Number(f.properties.j); movio = false; return; }      // se mueve el punto, no el mapa
      brocha = { trazo: [ll(e)], celdas: new Set(), ultimo: { x: e.point.x, y: e.point.y }, largo: 0 };
      marcar(e.point.x, e.point.y);
    };
    const soltar = () => {
      if (brocha) {
        const b = brocha, cierra = cierraBrocha();
        brocha = null;
        if (b.largo > 4) soltoEn = performance.now();            // un trazo, no un clic: que no ponga un punto
        if (cierra) {
          sinClicHasta.current = performance.now() + 500;
          cerrada = true; pintar();
          cb.current.alLazo?.(b.trazo, [...b.celdas]);
          setTimeout(() => { src.setData(VACIO); limpiarPincel(); }, 700);
          setLapiz(false);
        } else {
          if (b.largo > 4 && b.celdas.size) cb.current.alLazo?.(null, [...b.celdas]);
          limpiarPincel(); pintar();
        }
        return;
      }
      if (arrastra < 0) return;
      arrastra = -1;
      if (movio) soltoEn = performance.now();                    // tocar un punto sin moverlo cuenta como clic (cerrar en el primero)
      pintar();
    };
    const doble = (e: MapMouseEvent) => { e.preventDefault(); cerrar(); };
    const tecla = (e: KeyboardEvent) => {
      if (e.key === "Escape") setLapiz(false);
      else if (e.key === "Enter") cerrar();
      else if (e.key === "Backspace" || e.key === "Delete") { e.preventDefault(); deshacer(); }
    };
    m.on("click", clic); m.on("mousemove", mueve); m.on("dblclick", doble);
    m.on("mousedown", tomar); m.on("touchstart", tomar); m.on("mouseup", soltar); m.on("touchend", soltar);
    m.on("touchmove", mueve as unknown as (e: MapTouchEvent) => void);
    window.addEventListener("keydown", tecla);
    pintar();
    return () => {
      m.off("click", clic); m.off("mousemove", mueve); m.off("dblclick", doble);
      m.off("mousedown", tomar); m.off("touchstart", tomar); m.off("mouseup", soltar); m.off("touchend", soltar);
      m.off("touchmove", mueve as unknown as (e: MapTouchEvent) => void);
      window.removeEventListener("keydown", tecla);
      m.dragPan.enable();
      if (!cerrada) { src.setData(VACIO); limpiarPincel(); }  // cancelada: no queda nada; cerrada: se ve un momento y se borra sola
    };
  }, [lapiz, listo]);

  useEffect(() => {
    if (!listo) return;
    hayComunas.current = (comunas?.features.length ?? 0) > 0;
    (mapa.current?.getSource("comunas") as GeoJSONSource | undefined)?.setData(comunas ?? VACIO);
  }, [comunas, listo]);

  // Un punto por comuna para su nombre: el centro del polígono más grande. Solo cambia si cambian las comunas.
  const nombres = useMemo<GeoJSON.FeatureCollection>(() => ({
    type: "FeatureCollection",
    features: (comunas?.features ?? []).flatMap((f) => {
      if (f.geometry.type !== "MultiPolygon") return [];
      let mejor: [number, number] | null = null, areaMax = 0;
      for (const poly of f.geometry.coordinates) {
        const a = poly[0];
        let area = 0, cx = 0, cy = 0;
        for (let k = 0; k < a.length - 1; k++) {
          const w = a[k][0] * a[k + 1][1] - a[k + 1][0] * a[k][1];
          area += w; cx += (a[k][0] + a[k + 1][0]) * w; cy += (a[k][1] + a[k + 1][1]) * w;
        }
        if (Math.abs(area) > areaMax) { areaMax = Math.abs(area); mejor = [cx / (3 * area), cy / (3 * area)]; }
      }
      return mejor ? [{ type: "Feature" as const, properties: { n: String(f.properties?.c ?? "") }, geometry: { type: "Point" as const, coordinates: mejor } }] : [];
    }),
  }), [comunas?.features.length]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!listo) return;
    (mapa.current?.getSource("comunas-nombre") as GeoJSONSource | undefined)?.setData(nombres);
  }, [nombres, listo]);

  useEffect(() => {
    const m = mapa.current;
    if (!listo || !m) return;
    (m.getSource("capturas") as GeoJSONSource).setData(capturas ?? VACIO);
    (m.getSource("recorridos") as GeoJSONSource).setData(recorridos ?? VACIO);
  }, [capturas, recorridos, listo]);

  useEffect(() => {
    const m = mapa.current;
    if (!listo || !m || !corredor) return;
    // El corredor nuevo aparece desde transparente; si es el mismo trazado no parpadea.
    (m.getSource("corredor") as GeoJSONSource).setData(corredor);
    const clave = corredor.features.filter((f) => f.properties?.tipo === "ahora").map((f) => f.properties?.h3).join();
    if (clave === claveCorredor.current || menosMovimiento()) { claveCorredor.current = clave; return; }
    claveCorredor.current = clave;
    m.setPaintProperty("corredor", "fill-opacity", 0);
    const t = setTimeout(() => m.getLayer("corredor") && m.setPaintProperty("corredor", "fill-opacity", 0.92), 60);
    return () => clearTimeout(t);
  }, [corredor, listo]);

  useEffect(() => {
    const m = mapa.current;
    if (!listo || !m || cb.current.lapiz) return;   // mientras se pinta, el mapa no salta a lo ya marcado
    // Encuadre holgado: lo elegido queda a la vista con sus vecinas, sin acercarse de golpe.
    m.fitBounds(encuadre, { padding: 56, maxZoom: 12.2, duration: menosMovimiento() ? 0 : 900, essential: false });
  }, [encuadre, listo]);

  return (
    <div ref={cont} className="mapa" role="region" aria-label={etiqueta}>
      <div ref={nodo} style={{ position: "absolute", inset: 0 }} />
      <div className={`esqueleto${pintado ? " fuera" : ""}`} aria-hidden={!falla}><span>{falla ? "Este navegador no puede dibujar el mapa (necesita WebGL2)." : "Dibujando las comunas…"}</span></div>
      {pintado && actualizando && <div className="actualiza" role="status">Actualizando el mapa…</div>}
      {pintado && alLazo && (
        <div className="herramientas">
          <button type="button" className={`herr${lapiz ? " activa" : ""}`} aria-pressed={lapiz} onClick={() => setLapiz(!lapiz)}
            title="Arrastra para pintar cuadras y vuelve al inicio para rellenar la zona, o pon puntos unidos por rectas">
            <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 18L9 6l10 4-4 9z" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" /><circle cx="5" cy="18" r="2.2" fill="currentColor" /><circle cx="9" cy="6" r="2.2" fill="currentColor" /><circle cx="19" cy="10" r="2.2" fill="currentColor" /><circle cx="15" cy="19" r="2.2" fill="currentColor" /></svg>
            {lapiz ? "Cancelar" : "Dibujar zona"}
          </button>
          {lapiz && (
            <div className="herr-fila">
              <button type="button" className="herr" disabled={!nPuntos} onClick={() => accion.current.deshacer()}>Deshacer punto</button>
              <button type="button" className="herr listo" disabled={nPuntos < 3} onClick={() => accion.current.listo()}>Listo</button>
            </div>
          )}
        </div>
      )}
      {pintado && lapiz && <div className="pista" role="status">{nPuntos === 0
        ? "Arrastra para pintar cuadras; vuelve al inicio del trazo para rellenar la zona. También puedes poner puntos con clics."
        : nPuntos < 3
        ? `Toca el mapa para poner puntos (${nPuntos} de al menos 3). Los puntos se pueden arrastrar.`
        : `${nPuntos} puntos · ≈ ${areaKm2 < 1 ? `${Math.round(areaKm2 * 100)} ha` : `${areaKm2.toLocaleString("es-CL", { maximumFractionDigits: 2 })} km²`}. Toca el primer punto, haz doble clic o «Listo» para cerrar.`}</div>}
      {pintado && !lapiz && rueda === "apagada" && <div className="pista" aria-hidden="true">Haz clic en el mapa para acercar con la rueda</div>}
      {children}
    </div>
  );
}
