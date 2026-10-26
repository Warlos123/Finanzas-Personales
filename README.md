# Finanzas-Personales

Aplicación para llevar control de finanzas por medio de notificaciones del BCR conectando un dispositivo Android con una PC Linux. Todo local y privado.

- PC (Python + SQLite): importa correos "BCR Tarjetas" y SMS de SINPE Móvil, y muestra reportes.
- Android (Kotlin): captura los SMS del 4066 y los deja en una carpeta sincronizada con Syncthing.

Arquitectura, decisiones y estado del proyecto: ver [`CLAUDE.md`](CLAUDE.md).

## Instalación en la PC (Omarchy / Arch)

```bash
sudo pacman -S --needed python libsecret libnotify gnome-keyring sqlite
git clone <este repo> && cd Finanzas-Personales
python -m venv .venv
.venv/bin/pip install -e .

# Una sola vez: pide la contraseña de aplicación (no se muestra) y la guarda en el llavero.
.venv/bin/finanzas configurar-gmail TU_CORREO@gmail.com

# Primera importación (últimos 180 días) y luego automática cada 5 minutos.
.venv/bin/finanzas importar
scripts/instalar_systemd.sh
```

Comprobar que no hay duplicados:

```bash
sqlite3 ~/.local/share/finanzas/finanzas.db \
  "SELECT COUNT(*), COUNT(DISTINCT llave_unica) FROM transactions;"
```

## Desarrollo

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```
