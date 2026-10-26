#!/usr/bin/env bash
# Instala y activa el servicio + timer de usuario que importa cada 5 minutos.
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
bin="$repo/.venv/bin/finanzas"
if [ ! -x "$bin" ]; then
    echo "No existe $bin. Crea el venv primero: python -m venv .venv && .venv/bin/pip install -e ." >&2
    exit 1
fi

destino="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$destino"
sed "s|@FINANZAS_BIN@|$bin|" "$repo/systemd/finanzas-importar.service.in" > "$destino/finanzas-importar.service"
cp "$repo/systemd/finanzas-importar.timer" "$destino/finanzas-importar.timer"

systemctl --user daemon-reload
systemctl --user enable --now finanzas-importar.timer
echo "Timer activo:"
systemctl --user list-timers finanzas-importar.timer --no-pager
