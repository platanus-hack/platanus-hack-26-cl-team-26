# SINCA automático desde un PC con Linux en Chile

GitHub Actions trae cada noche la DMC (`.github/workflows/maximas.yml`), pero SINCA bloquea las conexiones
desde fuera de Chile. Este timer de systemd suma SINCA desde un PC del equipo. No necesita estar prendido a
una hora fija: SINCA guarda historial, y al prender completa los días que falten (últimos 14).

## Instalar (una vez)

```bash
git clone git@github.com:platanus-hack/platanus-hack-26-cl-team-26.git ~/verdeh3-sinca
cd ~/verdeh3-sinca
python3 -m venv .venv && .venv/bin/pip install pandas numpy pyarrow h3 requests
chmod +x scripts/completar_sinca.sh
PYTHON=.venv/bin/python scripts/completar_sinca.sh      # prueba a mano: debe decir "Subido" o "Nada nuevo"

mkdir -p ~/.config/systemd/user
cp scripts/systemd/verdeh3-sinca.service scripts/systemd/verdeh3-sinca.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now verdeh3-sinca.timer
loginctl enable-linger "$USER"                          # que corra aunque no haya sesión abierta
```

- El clon tiene que poder hacer `git push` sin preguntar nada: con una llave SSH en GitHub (como arriba) o
  `gh auth login`.
- Si se clona en otra carpeta, cambiar `%h/verdeh3-sinca` en el `.service`.

## Revisar

```bash
systemctl --user list-timers verdeh3-sinca.timer        # cuándo corre la próxima vez
journalctl --user -u verdeh3-sinca.service -n 30        # qué hizo la última vez
systemctl --user start verdeh3-sinca.service            # correrlo ahora
```

Desinstalar: `systemctl --user disable --now verdeh3-sinca.timer` y borrar los dos archivos de
`~/.config/systemd/user/`.
