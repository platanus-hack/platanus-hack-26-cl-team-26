"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import type { InfoComunas } from "@/lib/terreno";
import { formato } from "./movimiento";

// Filtro de comunas sobre el mapa. Se parte sin nada marcado (todo Santiago); tocar una comuna la suma y
// tocarla otra vez la quita. Lo elegido no oculta el resto: el mapa lo atenúa y encuadra lo elegido.
// Arriba a la derecha van las comunas elegidas (o la zona dibujada con el lápiz) y el botón para volver al inicio.
const sinTilde = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
const porNombre = (a: string, b: string) => a.localeCompare(b, "es");

export default function FiltroComunas({ info, elegidas, zona, alternar, sumar, reiniciar, sueloComuna, ocupado, error, sinResumen }: {
  info: InfoComunas;
  elegidas: string[];
  zona: number;                       // cuadras de la zona dibujada (0 si no hay)
  alternar: (c: string) => void;
  sumar: (cs: string[]) => void;
  reiniciar: () => void;
  sueloComuna: Map<string, number>;
  ocupado: boolean;
  error: string | null;
  sinResumen?: boolean;               // sin el panel de arriba a la derecha: solo un botón para volver al inicio
}) {
  const [abierto, setAbierto] = useState(false);
  const [busca, setBusca] = useState("");
  const boton = useRef<HTMLButtonElement>(null);
  const buscador = useRef<HTMLInputElement>(null);
  const nada = !elegidas.length && !zona;

  function cerrar() {
    setAbierto(false);
    boton.current?.focus();
  }
  useEffect(() => { if (abierto) setTimeout(() => buscador.current?.focus(), 50); }, [abierto]);

  const vec = useMemo(() => {
    const v = new Set<string>();
    for (const c of elegidas) for (const x of info.vecinas[c] ?? []) if (!elegidas.includes(x)) v.add(x);
    return [...v].sort(porNombre);
  }, [elegidas, info]);
  const q = sinTilde(busca.trim());
  const grupos: [string, string[]][] = [
    ["Elegidas", [...elegidas].sort(porNombre)],
    ["Vecinas de lo elegido", vec],
    [elegidas.length ? "Las demás" : `Las ${info.comunas.length} comunas`, info.comunas.filter((c) => !elegidas.includes(c) && !vec.includes(c)).sort(porNombre)],
  ];

  return (
    <>
      <button ref={boton} type="button" className="flota abre" aria-expanded={abierto} onClick={() => (abierto ? cerrar() : (setBusca(""), setAbierto(true)))}>
        <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M7 12h10M10 18h4" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" /></svg>
        Comunas {elegidas.length > 0 && <span className="cuenta num">{elegidas.length}</span>}
        {ocupado && <span className="nota" style={{ fontWeight: 500 }}>Calculando…</span>}
      </button>

      {sinResumen ? (
        (!nada || error) && (
          <div className="flota resumen-mapa solo" aria-live="polite">
            {!nada && <button type="button" className="mini volver" onClick={reiniciar}>↺ Volver a todo Santiago</button>}
            {error && <span className="aviso" role="alert">{error}</span>}
          </div>
        )
      ) : <div className="flota resumen-mapa" aria-live="polite">
        {nada ? <span className="t">Todo Santiago, {info.comunas.length} comunas</span> : (
          <span className="t quitar">
            {zona > 0 && <span className="chip zona num">Zona dibujada, {zona.toLocaleString("es-CL")} cuadras<button type="button" aria-label="Quitar la zona dibujada" onClick={reiniciar}>×</button></span>}
            {elegidas.length > 6 ? <span className="chip num">{elegidas.length} comunas</span> : [...elegidas].sort(porNombre).map((c) => (
              <span key={c} className="chip">{c}<button type="button" aria-label={`Quitar ${c}`} onClick={() => alternar(c)}>×</button></span>
            ))}
          </span>
        )}
        {nada
          ? <span className="nota">Doble clic en una comuna para elegirla, o encierra cuadras con el lápiz.</span>
          : <button type="button" className="mini volver" onClick={reiniciar}>↺ Volver a todo Santiago</button>}
        {error && <span className="aviso" role="alert" style={{ flexBasis: "100%" }}>{error}</span>}
      </div>}

      {abierto && (
        <aside className="cajon" aria-label="Elegir comunas" onKeyDown={(e) => { if (e.key === "Escape") cerrar(); }}>
          <header>
            <h2>Comunas</h2>
            <button type="button" className="cierra" aria-label="Cerrar" onClick={cerrar}>×</button>
          </header>
          <div className="acciones">
            <button type="button" className="mini" disabled={!vec.length} onClick={() => sumar(vec)}>Sumar vecinas</button>
            <button type="button" className="mini" disabled={nada} onClick={reiniciar}>↺ Volver a todo Santiago</button>
          </div>
          <input ref={buscador} type="search" placeholder="Buscar comuna" aria-label="Buscar comuna" value={busca} onChange={(e) => setBusca(e.target.value)} />
          <div className="lista">
            {grupos.map(([titulo, cs]) => {
              const vis = cs.filter((c) => sinTilde(c).includes(q));
              return vis.length ? (
                <div key={titulo}>
                  <h3>{titulo}</h3>
                  {vis.map((c) => (
                    <label key={c}>
                      <input type="checkbox" checked={elegidas.includes(c)} onChange={() => alternar(c)} />
                      <span>{c}</span>
                      <small className="num">{sueloComuna.has(c) ? `${formato(sueloComuna.get(c)!, 1)} °C` : ""}</small>
                    </label>
                  ))}
                </div>
              ) : null;
            })}
            {grupos.every(([, cs]) => !cs.some((c) => sinTilde(c).includes(q))) && <p className="nota" style={{ padding: 8 }}>Ninguna comuna se llama así.</p>}
          </div>
          <p className="nota pie">{nada ? "Sin nada marcado se ve todo Santiago. Marca una comuna para enfocarla." : `${elegidas.length} ${elegidas.length === 1 ? "elegida" : "elegidas"}${zona ? " y una zona dibujada" : ""}. Lo demás queda atenuado en el mapa.`}</p>
        </aside>
      )}
    </>
  );
}
