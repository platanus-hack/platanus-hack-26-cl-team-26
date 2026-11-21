"use client";
import { useEffect, useRef, useState } from "react";
import { formato, menosMovimiento } from "./movimiento";

// Número que cuenta hasta su valor al entrar a la vista, y de un valor al siguiente cuando cambia.
export default function Cifra({ valor, dec = 0, sufijo = "", duracion = 1100 }: {
  valor: number; dec?: number; sufijo?: string; duracion?: number;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const [mostrado, setMostrado] = useState(valor);
  const actual = useRef(valor);
  const visto = useRef(false);

  useEffect(() => {
    const el = ref.current;
    if (!el || menosMovimiento()) { setMostrado(valor); actual.current = valor; return; }
    let raf = 0;
    const animar = (desde: number) => {
      const t0 = performance.now();
      const paso = (t: number) => {
        const k = Math.min(1, (t - t0) / duracion);
        const v = desde + (valor - desde) * (1 - Math.pow(1 - k, 3));
        actual.current = v;
        setMostrado(v);
        if (k < 1) raf = requestAnimationFrame(paso);
      };
      raf = requestAnimationFrame(paso);
    };
    if (visto.current) { animar(actual.current); return () => cancelAnimationFrame(raf); }
    setMostrado(0);
    const io = new IntersectionObserver(([e]) => {
      if (e.isIntersecting) { visto.current = true; io.disconnect(); animar(0); }
    }, { threshold: 0.4 });
    io.observe(el);
    return () => { io.disconnect(); cancelAnimationFrame(raf); };
  }, [valor, dec, duracion]);

  return <span ref={ref} className="num">{formato(mostrado, dec)}{sufijo}</span>;
}
