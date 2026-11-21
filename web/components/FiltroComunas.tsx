"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import type { Cambio, Estado, InfoComunas } from "@/lib/terreno";
import { formato } from "./movimiento";

// Opción 3 del filtro: un solo botón "Comunas" sobre el mapa abre un cajón lateral con las elegidas,
// sus vecinas y las demás. Cada cambio se aplica al momento (agrupado en 400 ms) y el mapa lo muestra;
// quitar la última vuelve a la vista general del Gran Santiago. Arriba a la derecha, un resumen del área.
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

  const pendiente = useRef<ReturnType<typeof setTimeout>>(undefined);
  // Lo que llega del servidor (o de otro mapa de la página) manda mientras no haya un cambio en camino.
  const clave = [...sel].sort(porNombre).join("|");
  useEffect(() => { if (!pendiente.current) setBorrador(sel); }, [clave]); // eslint-disable-line react-hooks/exhaustive-deps

  function aplicar(nuevo: string[]) {
    const final = nuevo.length ? nuevo : info.comunas;   // sin comunas elegidas: vista general del Gran Santiago
    setBorrador(final);
    clearTimeout(pendiente.current);
    pendiente.current = setTimeout(() => {
      pendiente.current = undefined;
      const igual = final.length === sel.length && final.every((c) => sel.includes(c));
      if (!igual) cambiar({ comunas: [...final].sort(porNombre), distritos: [], zona: null });
    }, 400);
  }
  function abrir() {
    setBusca("");
    setAbierto(true);
  }
  function cerrar() {
    setAbierto(false);
    boton.current?.focus();
  }
  useEffect(() => { if (abierto) setTimeout(() => buscador.current?.focus(), 50); }, [abierto]);

  // Con las 34 a la vista no hay filtro: la lista sale sin marcas y marcar una la deja sola.
  const elegidas = borrador.length < total ? borrador : [];
  const vec = useMemo(() => vecinasDe(elegidas, info.vecinas), [elegidas.join("|"), info]); // eslint-disable-line react-hooks/exhaustive-deps
  const q = sinTilde(busca.trim());
  const grupos: [string, string[]][] = [
    ["Elegidas", [...elegidas].sort(porNombre)],
    ["Vecinas de lo elegido", vec],
    [elegidas.length ? "Las demás" : "Marca una para verla sola", info.comunas.filter((c) => !elegidas.includes(c) && !vec.includes(c)).sort(porNombre)],
  ];
  const alternar = (c: string) => aplicar(elegidas.includes(c) ? elegidas.filter((x) => x !== c) : [...elegidas, c]);

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
        {todas || sel.length > 6 ? <span className="t">{todas ? `Gran Santiago, ${total} comunas` : `${sel.length} comunas`}</span> : (
          <span className="t quitar">{sel.map((c) => (
            <span key={c} className="chip">{c}<button type="button" aria-label={`Quitar ${c}`} onClick={() => aplicar(elegidas.filter((x) => x !== c))}>×</button></span>
          ))}</span>
        )}
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
            <button type="button" className="cierra" aria-label="Cerrar" onClick={cerrar}>×</button>
          </header>
          <div className="acciones">
            <button type="button" className="mini" aria-pressed={borrador.length === total} onClick={() => aplicar(info.comunas)}>Las {total}</button>
            <button type="button" className="mini" disabled={!elegidas.length || !vec.length} onClick={() => aplicar([...elegidas, ...vec])}>Sumar vecinas</button>
            <button type="button" className="mini sola" disabled={borrador.length === total} onClick={() => aplicar([])}>Limpiar</button>
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
          <p className="nota pie">{borrador.length === total ? `Las ${total} comunas: vista general. Marca una para verla sola.` : `${borrador.length} ${borrador.length === 1 ? "elegida" : "elegidas"}. Quitar la última vuelve a la vista general.`}</p>
        </aside>
      )}
    </>
  );
}
