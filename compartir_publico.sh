#!/usr/bin/env bash
# VerdeH3 - Exponer el servidor (mapa) a una URL pública HTTPS
# Usa Cloudflare Quick Tunnels (gratis, sin registro, sin abrir puertos). El GPS del teléfono exige HTTPS.
# Antes, en otra terminal:  TERRENO_CLAVE=<clave> python -m terreno.servidor --puerto 8000

PUERTO=8000
DIR_ACTUAL="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=========================================================="
echo "🌿 VerdeH3 · Lanzador de Acceso Público Remoto"
echo "=========================================================="
echo "1. Mapa en este computador: http://localhost:$PUERTO/mapa"
echo "2. Generando enlace público HTTPS con Cloudflare..."
echo "   Mapa para el jurado:           https://<túnel>/mapa?k=<clave>"
echo "=========================================================="

"$DIR_ACTUAL/bin/cloudflared" tunnel --url "http://localhost:$PUERTO"
