#!/usr/bin/env bash
# Abre la UI como ventana de app. Atajo de Hyprland: SUPER+CTRL+SHIFT+F.
set -euo pipefail

puerto=8765
url="http://127.0.0.1:$puerto"
dir_scripts="$(cd "$(dirname "$0")" && pwd)"
# Python del sistema (el de pacman trae python-gobject); se puede cambiar para pruebas.
python_sistema="${FINANZAS_PYTHON:-/usr/bin/python3}"
systemctl --user start finanzas-ui.service
# Espera hasta ~5 s a que el servidor acepte conexiones.
for _ in $(seq 1 50); do
    if (exec 3<>"/dev/tcp/127.0.0.1/$puerto") 2>/dev/null; then
        break
    fi
    sleep 0.1
done

# 1) Ventana propia con WebKitGTK si están python-gobject y webkitgtk-6.0.
if "$python_sistema" -c 'import gi; gi.require_version("Gtk", "4.0"); gi.require_version("WebKit", "6.0")' 2>/dev/null; then
    exec "$python_sistema" "$dir_scripts/ventana.py"
fi

# 2) Primer navegador basado en Chromium que exista, en modo app (ventana sin pestañas).
navegadores=(chromium brave google-chrome-stable vivaldi-stable microsoft-edge-stable)
for ((i = 0; i < ${#navegadores[@]}; i++)); do
    if command -v "${navegadores[i]}" >/dev/null 2>&1; then
        exec "${navegadores[i]}" --app="$url"
    fi
done
# 3) Firefox no tiene modo app: se abre en una ventana aparte.
if command -v firefox >/dev/null 2>&1; then
    exec firefox --new-window "$url"
fi
exec xdg-open "$url"
