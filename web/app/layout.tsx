import type { Metadata } from "next";
import { Archivo, Fraunces } from "next/font/google";
import "maplibre-gl/dist/maplibre-gl.css";
import "./globals.css";

const archivo = Archivo({ subsets: ["latin"], axes: ["wdth"], variable: "--f-archivo", display: "swap" });
const fraunces = Fraunces({ subsets: ["latin"], style: "italic", variable: "--f-fraunces", display: "swap" });

export const metadata: Metadata = {
  title: "VerdeH3 · Sombra donde más falta",
  description: "Calor del suelo, copa de árboles y personas, cuadra por cuadra, para planificar corredores verdes en Santiago.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es-CL" className={`${archivo.variable} ${fraunces.variable}`} suppressHydrationWarning>
      <head>
        {/* Las animaciones de entrada solo se activan si corre JS; sin JS todo queda visible */}
        <script dangerouslySetInnerHTML={{ __html: "document.documentElement.classList.add('js')" }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
