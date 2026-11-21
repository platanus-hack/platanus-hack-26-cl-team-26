import type { Metadata } from "next";
import { Archivo, DM_Serif_Display, Fraunces } from "next/font/google";
import "maplibre-gl/dist/maplibre-gl.css";
import "./globals.css";

const archivo = Archivo({ subsets: ["latin"], axes: ["wdth"], variable: "--f-archivo", display: "swap" });
const dmSerif = DM_Serif_Display({ subsets: ["latin"], weight: "400", style: ["normal", "italic"], variable: "--f-titular", display: "swap" });
const fraunces = Fraunces({ subsets: ["latin"], style: "italic", variable: "--f-fraunces", display: "swap" });

export const metadata: Metadata = {
  title: "Viridis · Donde se necesita el verde",
  description: "Calor del suelo, copa de árboles y personas, cuadra por cuadra, para planificar corredores verdes en Santiago.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es-CL" className={`${archivo.variable} ${fraunces.variable} ${dmSerif.variable}`} suppressHydrationWarning>
      <head>
        {/* Las animaciones de entrada solo se activan si corre JS; sin JS todo queda visible. Si React no
            alcanza a hidratar (un chunk que no carga, un navegador viejo), a los 2,5 s se quita .js y todo se ve. */}
        <script dangerouslySetInnerHTML={{ __html: "document.documentElement.classList.add('js');setTimeout(function(){if(!window.__revela)document.documentElement.classList.remove('js')},2500)" }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
