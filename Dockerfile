FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Un solo servidor: mapa en /mapa, captura del teléfono en /?k=<clave>. Render define PORT.
ENV PORT=8000
EXPOSE 8000

HEALTHCHECK CMD curl --fail http://localhost:${PORT}/api/salud

# TERRENO_CLAVE y ANTHROPIC_API_KEY se configuran como variables de entorno (nunca en la imagen).
CMD ["sh", "-c", "python -m terreno.servidor --host 0.0.0.0 --puerto ${PORT}"]
