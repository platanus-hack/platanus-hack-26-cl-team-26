# Viridis en un solo servicio: el sitio (Next.js exportado a archivos estáticos) y el servidor de terreno
# (FastAPI) en el mismo contenedor y el mismo enlace:
#   /          sitio Viridis           /captura   página del teléfono (foto, video, escuchar aves; ?k=<clave>)
#   /api/...   datos, corredor, etc.   /mapa      mapa de respaldo
# Render define PORT y las variables secretas (ver render.yaml).

# 1) Sitio: npm run exportar deja los archivos en web/out
FROM node:22-slim AS sitio
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run exportar

# 2) Servidor
FROM python:3.12-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=sitio /web/out ./web/out

# Un solo servidor: el sitio en /, el mapa en /mapa y la API. Render define PORT.
ENV PORT=8000
EXPOSE 8000

HEALTHCHECK CMD curl --fail http://localhost:${PORT}/api/salud

# TERRENO_CLAVE, ANTHROPIC_API_KEY, DMC_USUARIO y DMC_TOKEN llegan como variables de entorno (nunca en la imagen).
CMD ["sh", "-c", "python -m terreno.servidor --host 0.0.0.0 --puerto ${PORT}"]
