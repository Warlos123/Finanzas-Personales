#!/usr/bin/env bash
# Abre la UI como ventana de app. Atajo de Hyprland: SUPER+CTRL+SHIFT+F.
set -euo pipefail

puerto=8765
systemctl --user start finanzas-ui.service
# Espera hasta ~5 s a que el servidor acepte conexiones.
for _ in $(seq 1 50); do
    if (exec 3<>"/dev/tcp/127.0.0.1/$puerto") 2>/dev/null; then
        break
    fi
    sleep 0.1
done
exec chromium --app="http://127.0.0.1:$puerto"
