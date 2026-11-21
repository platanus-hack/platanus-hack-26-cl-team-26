"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import type { Cambio, Estado, InfoComunas } from "@/lib/terreno";
import { formato } from "./movimiento";

// Opción 3 del filtro: un solo botón "Comunas" sobre el mapa abre un cajón lateral con las elegidas,
// sus vecinas y las demás. Se edita un borrador y se guarda al cerrar (una sola vuelta al servidor).
// Arriba a la derecha queda un resumen chico del área.
const sinTilde = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
const porNombre = (a: string, b: string) => a.localeCompare(b, "es");

function vecinasDe(sel: string[], vecinas: Record<string, string[]>) {
  const v = new Set<string>();
  for (const c of sel) for (const x of vecinas[c] ?? []) if (!sel.includes(x)) v.add(x);
  return [...v].sort(porNombre);
}

export default function FiltroComunas({ info, estado, ocupado, error, cambiar, sueloComuna }: {
  info: InfoComunas;
  estado: Estado;
  ocupado: boolean;
  error: string | null;
  cambiar: (c: Cambio) => void;
  sueloComuna: Map<string, number>;
}) {
  const sel = estado.seleccion;
  const total = info.comunas.length;
  const todas = sel.length === total;
  const [abierto, setAbierto] = useState(false);
  const [borrador, setBorrador] = useState<string[]>(sel);
  const [busca, setBusca] = useState("");
  const boton = useRef<HTMLButtonElement>(null);
  const buscador = useRef<HTMLInputElement>(null);

  function abrir() {
    setBorrador(sel);
    setBusca("");
    setAbierto(true);
  }
  function cerrar() {
    setAbierto(false);
    boton.current?.focus();
    const nuevo = borrador.length ? borrador : info.comunas;   // sin comunas elegidas se ve todo el Gran Santiago
    const igual = nuevo.length === sel.length && nuevo.every((c) => sel.includes(c));
    if (!igual) cambiar({ comunas: [...nuevo].sort(porNombre), distritos: [], zona: null });
  }
  useEffect(() => { if (abierto) setTimeout(() => buscador.current?.focus(), 50); }, [abierto]);

  const vec = useMemo(() => vecinasDe(borrador, info.vecinas), [borrador, info]);
  const q = sinTilde(busca.trim());
  const grupos: [string, string[]][] = [
    ["Elegidas", [...borrador].sort(porNombre)],
    ["Vecinas de lo elegido", vec],
    ["Las demás", info.comunas.filter((c) => !borrador.includes(c) && !vec.includes(c)).sort(porNombre)],
  ];
  const alternar = (c: string) => setBorrador((b) => (b.includes(c) ? b.filter((x) => x !== c) : [...b, c]));

  const H = estado.hex;
  const resumen = useMemo(() => {
    const lst = H.lst.filter((x): x is number => x != null), copa = H.copa.filter((x): x is number => x != null);
    const med = (xs: number[]) => (xs.length ? xs.reduce((s, x) => s + x, 0) / xs.length : 0);
    return { cuadras: H.h.length, personas: H.pob.reduce((s, x) => s + x, 0), suelo: med(lst), copa: med(copa) };
  }, [H]);

  return (
    <>
      <button ref={boton} type="button" className="flota abre" aria-expanded={abierto} onClick={abierto ? cerrar : abrir}>
        <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M7 12h10M10 18h4" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" /></svg>
        Comunas <span className="cuenta num">{todas ? total : sel.length}</span>
        {ocupado && <span className="nota" style={{ fontWeight: 500 }}>Calculando…</span>}
      </button>

      <div className="flota resumen-mapa num" aria-live="polite">
        <span className="t">{todas ? `Gran Santiago, ${total} comunas` : sel.length <= 3 ? sel.join(", ") : `${sel.length} comunas`}</span>
        <span><b>{resumen.cuadras.toLocaleString("es-CL")}</b> cuadras</span>
        <span><b>{resumen.personas.toLocaleString("es-CL")}</b> personas</span>
        <span><b>{formato(resumen.suelo, 1)} °C</b> suelo</span>
        <span><b>{formato(resumen.copa, 1)} %</b> copa</span>
        {error && <span className="aviso" role="alert" style={{ flexBasis: "100%" }}>{error}</span>}
      </div>

      {abierto && (
        <aside className="cajon" aria-label="Elegir comunas" onKeyDown={(e) => { if (e.key === "Escape") cerrar(); }}>
          <header>
            <h2>Comunas</h2>
            <button type="button" className="cierra" aria-label="Guardar y cerrar" onClick={cerrar}>×</button>
          </header>
          <div className="acciones">
            <button type="button" className="mini" aria-pressed={borrador.length === total} onClick={() => setBorrador(info.comunas)}>Las {total}</button>
            <button type="button" className="mini" disabled={!borrador.length || !vec.length} onClick={() => setBorrador([...borrador, ...vec])}>Sumar vecinas</button>
            <button type="button" className="mini sola" disabled={!borrador.length} onClick={() => setBorrador([])}>Limpiar</button>
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
                      <input type="checkbox" checked={borrador.includes(c)} onChange={() => alternar(c)} />
                      <span>{c}</span>
                      <small className="num">{sueloComuna.has(c) ? `${formato(sueloComuna.get(c)!, 1)} °C` : ""}</small>
                    </label>
                  ))}
                </div>
              ) : null;
            })}
            {grupos.every(([, cs]) => !cs.some((c) => sinTilde(c).includes(q))) && <p className="nota" style={{ padding: 8 }}>Ninguna comuna se llama así.</p>}
          </div>
          <p className="nota pie">{borrador.length ? `${borrador.length} elegidas.` : "Sin comunas elegidas: se verá todo el Gran Santiago."} Se guarda al cerrar.</p>
        </aside>
      )}
    </>
  );
}
