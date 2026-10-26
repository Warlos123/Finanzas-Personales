# Finanzas-Personales

Aplicación para llevar control de finanzas por medio de notificaciones del BCR conectando un dispositivo Android con una PC Linux. Todo local y privado.

- PC (Python + SQLite): importa correos "BCR Tarjetas" y SMS de SINPE Móvil, y muestra reportes.
- Android (Kotlin): captura los SMS del 4066 y los deja en una carpeta sincronizada con Syncthing.

Arquitectura, decisiones y estado del proyecto: ver [`CLAUDE.md`](CLAUDE.md).

## Desarrollo

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```
