#!/usr/bin/env bash
# VerdeH3 - Exponer Streamlit a una URL pública HTTPS mundial (sin localhost)
# Usa Cloudflare Quick Tunnels (gratis, sin registro, sin abrir puertos)

PUERTO=8501
DIR_ACTUAL="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=========================================================="
echo "🌿 VerdeH3 · Lanzador de Acceso Público Remoto"
echo "=========================================================="
echo "1. Tu IP local en el recinto es: $(hostname -I | awk '{print $1}'):$PUERTO"
echo "2. Generando enlace público HTTPS mundial con Cloudflare..."
echo "   (Cualquier persona o jurado podrá abrirlo desde su teléfono)"
echo "=========================================================="

"$DIR_ACTUAL/bin/cloudflared" tunnel --url "http://localhost:$PUERTO"
