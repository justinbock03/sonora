# Sonora

Reproductor de música para Windows, con diseño oscuro, minireproductor flotante y **letras
sincronizadas** que se iluminan al ritmo de la canción.

## Descargar y usar

1. Ve a **[Releases](https://github.com/justinbock03/sonora/releases)** y descarga el
   `Sonora-X.Y-portable.zip` de la versión más reciente (en *Assets*).
2. Descomprímelo en un lugar fijo, por ejemplo `Documentos\Sonora`.
3. Ejecuta `Crear acceso directo.bat`: aparecerá **Sonora 2** en el Escritorio y en el menú Inicio.
4. Abre Sonora y pulsa **Agregar carpeta** para elegir dónde está tu música.

No hace falta instalar nada más (ni Python). Si Windows muestra «Windows protegió su PC», pulsa
*Más información* → *Ejecutar de todas formas*: el programa no tiene firma digital.

## Qué hace

- Reproduce MP3, FLAC, WAV, OGG, OPUS, M4A/AAC, WMA, AIFF, ALAC, APE y más.
- Biblioteca por canciones, álbumes, artistas y carpetas, con búsqueda y varias formas de ordenar.
- La interfaz toma el color de la carátula que suena.
- Minireproductor siempre visible, teclas multimedia y botones en la barra de tareas.
- Letras desde archivos `.lrc`, la propia canción o [LRCLIB](https://lrclib.net) (NetEase como respaldo opcional).
- Editor para escribir y sincronizar letras, y publicarlas en LRCLIB si quieres.

Atajos: **Espacio** reproducir/pausar · **Ctrl+L** letra · **Ctrl+←/→** anterior/siguiente ·
**Ctrl+M** minireproductor · **F5** actualizar biblioteca.

## Para desarrolladores

Python 3.14 + PySide6 + mutagen. Ejecutar con `pythonw Sonora.pyw`; compilar el `.exe` y el ZIP con
`powershell -ExecutionPolicy Bypass -File tools\build.ps1`. Detalles en `DESARROLLO.md`; cambios en
`HISTORIAL.md`.
