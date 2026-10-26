#!/usr/bin/env python3
"""Ventana propia para la UI de Finanzas (GTK 4 + WebKitGTK 6), sin navegador.

Se corre con el Python del sistema, que trae los bindings de GTK:
    sudo pacman -S python-gobject webkitgtk-6.0
Es una sola instancia: si ya está abierta, volver a lanzarla la trae al frente.
"""

import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("WebKit", "6.0")
from gi.repository import Gtk, WebKit  # noqa: E402

URL = "http://127.0.0.1:8765"
# También es el app_id en Wayland: sirve para reglas de ventana de Hyprland.
ID_APP = "cr.finanzas.Finanzas"


def _activar(app: Gtk.Application) -> None:
    ventanas = app.get_windows()
    if ventanas:
        ventanas[0].present()
        return
    ventana = Gtk.ApplicationWindow(application=app, title="Finanzas")
    ventana.set_default_size(1280, 860)
    vista = WebKit.WebView()
    vista.load_uri(URL)
    ventana.set_child(vista)
    ventana.present()


def main() -> int:
    app = Gtk.Application(application_id=ID_APP)
    app.connect("activate", _activar)
    return app.run(sys.argv[:1])


if __name__ == "__main__":
    sys.exit(main())
