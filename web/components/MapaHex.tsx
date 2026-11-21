"use client";
import { useEffect, useRef, useState } from "react";
import type { ExpressionSpecification, GeoJSONSource, LngLatBoundsLike, Map as MapaML, Popup } from "maplibre-gl";
import { menosMovimiento, useVisible } from "./movimiento";

// Mapa base: Carto Positron teñido con la paleta crema y salvia. Encima, en este orden:
// hexágonos (una capa de relleno por vista; al cambiar de vista se cruzan las opacidades),
// contornos de comuna (del servidor de terreno; se tocan para elegir el área), corredor
// (relleno del actual, línea punteada del de sin terreno, magenta donde se verificó en terreno),
// y capturas en terreno con sus recorridos.
const ESTILO = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";
const OPACIDAD = 0.82;
const VACIO: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

export type Capa = { id: string; color: ExpressionSpecification };
// Lo elegido: índices de comuna (propiedad c de cada cuadra) o cuadras sueltas (propiedad i). null = todo Santiago.
export type Foco = { comunas: number[]; hexes: number[] } | null;
const TENUE = 0.22;

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

export default function MapaHex({ datos, capas, activa, corredor, comunas, distritos, capturas, recorridos, popupCaptura,
  encuadre, foco = null, alPasar, alComuna, alLazo, etiqueta, children }: {
  datos: GeoJSON.FeatureCollection;
  capas: Capa[];
  activa: string;
  corredor?: GeoJSON.FeatureCollection;      // polígonos con propiedad tipo: "ahora" | "antes" | "verificado"
  comunas?: GeoJSON.FeatureCollection;       // contornos con propiedades c (nombre) y est: sel | otra
  distritos?: GeoJSON.FeatureCollection;     // líneas entre sectores (distritos censales) de una misma comuna
  capturas?: GeoJSON.FeatureCollection;      // puntos con propiedad color
  recorridos?: GeoJSON.FeatureCollection;
  popupCaptura?: (props: Record<string, unknown>) => string;
  encuadre: LngLatBoundsLike;
  foco?: Foco;
  alPasar?: (i: number | null) => void;      // cuadra bajo el puntero
  alComuna?: (c: string) => void;            // tocar una cuadra o comuna: suma o quita su comuna
  alLazo?: (anillo: [number, number][]) => void;  // zona dibujada con el lápiz, en [lng, lat]
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
  const [lapiz, setLapiz] = useState(false);
  const pasado = useRef<number | null>(null);
  const sinClicHasta = useRef(0);   // al soltar el lápiz el mapa dispara un clic que no debe elegir comuna
  const cb = useRef({ alPasar, alComuna, alLazo, popupCaptura, activa, datos, lapiz });
  cb.current = { alPasar, alComuna, alLazo, popupCaptura, activa, datos, lapiz };
  const inicial = useRef({ datos, capas, activa, encuadre });
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
        nuevo.addSource("hex", { type: "geojson", data: ini.datos, promoteId: "i" });
        for (const c of ini.capas) {
          nuevo.addLayer({
            id: c.id, type: "fill", source: "hex",
            layout: { visibility: c.id === ini.activa ? "visible" : "none" },
            paint: { "fill-color": c.color, "fill-opacity": OPACIDAD, "fill-opacity-transition": fundido, "fill-antialias": false },
          });
        }
        // Con todo el Gran Santiago a la vista los bordes de 13 mil cuadras solo ensucian y cuestan; aparecen al acercar.
        nuevo.addLayer({
          id: "borde", type: "line", source: "hex", minzoom: 11,
          paint: { "line-color": "#F6F1E4", "line-width": 0.35, "line-opacity": ["interpolate", ["linear"], ["zoom"], 11, 0, 12, 1] },
        });
        nuevo.addSource("elegida", { type: "geojson", data: VACIO });
        nuevo.addLayer({ id: "elegida", type: "line", source: "elegida", paint: { "line-color": "#22281A", "line-width": 2.2 } });
        // Sectores: raya fina punteada entre distritos de una misma comuna, más visible al acercar.
        nuevo.addSource("distritos", { type: "geojson", data: VACIO });
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
        nuevo.addSource("comunas", { type: "geojson", data: VACIO });
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
          paint: { "fill-color": "#22301A", "fill-opacity": 0.92, "fill-opacity-transition": { duration: menosMovimiento() ? 0 : 700 } },
        });
        // Contorno grueso para que el corredor se distinga aun con el área completa a la vista.
        nuevo.addLayer({
          id: "corredor-borde", type: "line", source: "corredor", filter: ["==", ["get", "tipo"], "ahora"],
          paint: { "line-color": "#22301A", "line-width": ["interpolate", ["linear"], ["zoom"], 9, 3, 13, 1] },
        });
        nuevo.addLayer({
          id: "corredor-antes", type: "line", source: "corredor", filter: ["==", ["get", "tipo"], "antes"],
          paint: { "line-color": "#22281A", "line-width": 1.6, "line-dasharray": [2, 2] },
        });
        nuevo.addLayer({
          id: "corredor-verificado", type: "line", source: "corredor", filter: ["==", ["get", "tipo"], "verificado"],
          paint: { "line-color": "#B0398B", "line-width": 3 },
        });
        nuevo.addSource("recorridos", { type: "geojson", data: VACIO });
        nuevo.addLayer({ id: "recorridos", type: "line", source: "recorridos", paint: { "line-color": "#6B3FA0", "line-width": 4, "line-opacity": 0.85 } });
        nuevo.addSource("lazo", { type: "geojson", data: VACIO });
        nuevo.addLayer({ id: "lazo-relleno", type: "fill", source: "lazo", paint: { "fill-color": "#966222", "fill-opacity": 0.12 } });
        nuevo.addLayer({ id: "lazo", type: "line", source: "lazo", layout: { "line-join": "round", "line-cap": "round" }, paint: { "line-color": "#22281A", "line-width": 2.4, "line-dasharray": [1.5, 1.2] } });
        nuevo.addSource("capturas", { type: "geojson", data: VACIO });
        nuevo.addLayer({
          id: "capturas", type: "circle", source: "capturas",
          paint: { "circle-radius": 7, "circle-color": ["get", "color"], "circle-stroke-color": "#FFFDF6", "circle-stroke-width": 2 },
        });

        // Un toque: captura → su foto; cuadra o comuna → sumar o quitar su comuna. Con el lápiz activo no se elige nada.
        nuevo.on("click", (e) => {
          if (cb.current.lapiz || performance.now() < sinClicHasta.current) return;
          const cap = nuevo.queryRenderedFeatures(e.point, { layers: ["capturas"] })[0];
          if (cap && cb.current.popupCaptura) {
            popup?.remove();
            popup = new ml.Popup({ maxWidth: "260px" }).setLngLat(e.lngLat).setHTML(cb.current.popupCaptura(cap.properties)).addTo(nuevo);
            return;
          }
          const hex = nuevo.getLayer(cb.current.activa) ? nuevo.queryRenderedFeatures(e.point, { layers: [cb.current.activa] })[0] : undefined;
          if (hex && hex.properties.cn) { cb.current.alComuna?.(String(hex.properties.cn)); return; }
          const com = nuevo.queryRenderedFeatures(e.point, { layers: ["comunas-relleno"] })[0];
          if (com) cb.current.alComuna?.(String(com.properties.c));
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
  const claveFoco = foco ? `${foco.comunas.join()}|${foco.hexes.length}:${foco.hexes.slice(0, 50).join()}` : "";
  useEffect(() => {
    const m = mapa.current;
    if (!listo || !m) return;
    const op: ExpressionSpecification | number = foco
      ? ["case", ["any", ["in", ["get", "c"], ["literal", foco.comunas]], ["in", ["get", "i"], ["literal", foco.hexes]]], OPACIDAD, TENUE]
      : OPACIDAD;
    for (const c of capas) if (m.getLayer(c.id)) m.setPaintProperty(c.id, "fill-opacity", op);
  }, [claveFoco, capas, listo]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!listo) return;
    (mapa.current?.getSource("distritos") as GeoJSONSource | undefined)?.setData(distritos ?? VACIO);
  }, [distritos, listo]);

  // Lápiz: con él activo el mapa no se arrastra; se dibuja una zona y al soltar se entrega su contorno.
  useEffect(() => {
    const m = mapa.current;
    if (!listo || !m) return;
    const cont = m.getCanvasContainer();
    if (!lapiz) {
      m.dragPan.enable(); m.touchZoomRotate.enable(); m.doubleClickZoom.enable();
      cont.style.cursor = "";
      return;
    }
    m.dragPan.disable(); m.touchZoomRotate.disable(); m.doubleClickZoom.disable();
    cont.style.cursor = "crosshair";
    const lazo = m.getSource("lazo") as GeoJSONSource;
    let pts: [number, number][] = [], ult: [number, number] | null = null, dibuja = false;
    const pintar = (cerrar: boolean) => lazo.setData(pts.length < 2 ? VACIO : {
      type: "FeatureCollection", features: [cerrar && pts.length > 2
        ? { type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [[...pts, pts[0]]] } }
        : { type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: pts } }],
    });
    const punto = (e: PointerEvent): [number, number] => { const r = cont.getBoundingClientRect(); const ll = m.unproject([e.clientX - r.left, e.clientY - r.top]); return [ll.lng, ll.lat]; };
    const abajo = (e: PointerEvent) => {
      if (e.button !== 0) return;
      dibuja = true; cont.setPointerCapture(e.pointerId);
      pts = [punto(e)]; ult = [e.clientX, e.clientY];
    };
    const mueve = (e: PointerEvent) => {
      if (!dibuja || !ult || Math.hypot(e.clientX - ult[0], e.clientY - ult[1]) < 4) return;
      ult = [e.clientX, e.clientY]; pts.push(punto(e)); pintar(false);
    };
    const arriba = () => {
      if (!dibuja) return;
      dibuja = false;
      sinClicHasta.current = performance.now() + 500;
      if (pts.length > 2) { pintar(true); cb.current.alLazo?.(pts); }
      setTimeout(() => lazo.setData(VACIO), 700);
      setLapiz(false);
    };
    cont.style.touchAction = "none";
    cont.addEventListener("pointerdown", abajo);
    cont.addEventListener("pointermove", mueve);
    cont.addEventListener("pointerup", arriba);
    cont.addEventListener("pointercancel", arriba);
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setLapiz(false); };
    window.addEventListener("keydown", esc);
    return () => {
      cont.removeEventListener("pointerdown", abajo); cont.removeEventListener("pointermove", mueve);
      cont.removeEventListener("pointerup", arriba); cont.removeEventListener("pointercancel", arriba);
      window.removeEventListener("keydown", esc); cont.style.touchAction = "";
    };
  }, [lapiz, listo]);

  useEffect(() => {
    if (!listo) return;
    hayComunas.current = (comunas?.features.length ?? 0) > 0;
    (mapa.current?.getSource("comunas") as GeoJSONSource | undefined)?.setData(comunas ?? VACIO);
  }, [comunas, listo]);

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
    if (!listo || !m) return;
    m.fitBounds(encuadre, { padding: 32, duration: menosMovimiento() ? 0 : 900, essential: false });
  }, [encuadre, listo]);

  return (
    <div ref={cont} className="mapa" role="region" aria-label={etiqueta}>
      <div ref={nodo} style={{ position: "absolute", inset: 0 }} />
      <div className={`esqueleto${pintado ? " fuera" : ""}`} aria-hidden={!falla}><span>{falla ? "Este navegador no puede dibujar el mapa (necesita WebGL2)." : "Dibujando las comunas…"}</span></div>
      {pintado && actualizando && <div className="actualiza" role="status">Actualizando el mapa…</div>}
      {pintado && alLazo && (
        <div className="herramientas">
          <button type="button" className={`herr${lapiz ? " activa" : ""}`} aria-pressed={lapiz} onClick={() => setLapiz(!lapiz)}
            title="Encierra cuadras dibujando con el lápiz">
            <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20l1-4L16 5l3 3L8 19l-4 1zM14 7l3 3" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" /></svg>
            {lapiz ? "Dibuja la zona" : "Lápiz"}
          </button>
        </div>
      )}
      {pintado && lapiz && <div className="pista" role="status">Mantén apretado y encierra las cuadras. Esc para cancelar.</div>}
      {pintado && !lapiz && rueda === "apagada" && <div className="pista" aria-hidden="true">Haz clic en el mapa para acercar con la rueda</div>}
      {children}
    </div>
  );
}
