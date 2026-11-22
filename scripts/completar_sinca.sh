#!/usr/bin/env bash
# Suma SINCA a las máximas del día y lo sube al repo. Tiene que correr en un PC en Chile: SINCA responde 403
# a las conexiones desde fuera (por eso GitHub Actions trae solo la DMC). Lo llama el timer de
# scripts/systemd/; si el PC estuvo apagado, al prender completa todos los días que falten (hasta 14).
# Usar un clon aparte del repo, solo para esto: el script hace pull, commit y push.
set -euo pipefail
cd "$(dirname "$0")/.."
git pull --ff-only --quiet
"${PYTHON:-python3}" maximas.py --completar
git add data/maximas data/live_h3.parquet
if git diff --cached --quiet; then
    echo "Nada nuevo que subir"
    exit 0
fi
git commit --quiet -m "Maximas del dia: SINCA desde Chile"
git pull --rebase --quiet
git push --quiet
echo "Subido"
