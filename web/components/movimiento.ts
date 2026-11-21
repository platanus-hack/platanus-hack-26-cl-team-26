"use client";
import { useEffect, useRef, useState } from "react";

export function menosMovimiento() {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

// Marca el elemento con .visto la primera vez que entra a la vista.
export function useRevela<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(([e]) => {
      if (e.isIntersecting) { el.classList.add("visto"); io.disconnect(); }
    }, { threshold: 0.12 });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return ref;
}

export function useVisible<T extends HTMLElement>(margen = "200px") {
  const ref = useRef<T>(null);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(([e]) => {
      if (e.isIntersecting) { setVisible(true); io.disconnect(); }
    }, { rootMargin: margen });
    io.observe(el);
    return () => io.disconnect();
  }, [margen]);
  return [ref, visible] as const;
}

export const formato = (x: number, dec = 0) =>
  x.toLocaleString("es-CL", { minimumFractionDigits: dec, maximumFractionDigits: dec });
