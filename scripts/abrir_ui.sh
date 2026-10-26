#!/usr/bin/env bash
# Abre la UI como ventana de app. Atajo de Hyprland: SUPER+CTRL+SHIFT+F.
set -euo pipefail

puerto=8765
url="http://127.0.0.1:$puerto"
systemctl --user start finanzas-ui.service
# Espera hasta ~5 s a que el servidor acepte conexiones.
for _ in $(seq 1 50); do
    if (exec 3<>"/dev/tcp/127.0.0.1/$puerto") 2>/dev/null; then
        break
    fi
    sleep 0.1
done

# Primer navegador basado en Chromium que exista, en modo app (ventana sin pestañas).
navegadores=(chromium brave google-chrome-stable vivaldi-stable microsoft-edge-stable)
for ((i = 0; i < ${#navegadores[@]}; i++)); do
    if command -v "${navegadores[i]}" >/dev/null 2>&1; then
        exec "${navegadores[i]}" --app="$url"
    fi
done
# Sin ninguno: se abre como pestaña en el navegador por defecto.
exec xdg-open "$url"
