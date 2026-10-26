#!/usr/bin/env bash
# Instala y activa las unidades de usuario: importación cada 5 minutos y UI web local.
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
sed "s|@FINANZAS_BIN@|$bin|" "$repo/systemd/finanzas-ui.service.in" > "$destino/finanzas-ui.service"
cp "$repo/systemd/finanzas-importar.timer" "$destino/finanzas-importar.timer"

systemctl --user daemon-reload
systemctl --user enable --now finanzas-importar.timer
systemctl --user enable finanzas-ui.service
systemctl --user restart finanzas-ui.service
echo "Timer activo:"
systemctl --user list-timers finanzas-importar.timer --no-pager
echo
echo "UI en http://127.0.0.1:8765. Para el atajo SUPER+CTRL+SHIFT+F agrega a tus bindings de Omarchy (Lua):"
echo "o.bind(\"SUPER + CTRL + SHIFT + F\", \"Finanzas\", \"$repo/scripts/abrir_ui.sh\")"
