# Historial de cambios de Sonora

Lo más reciente va primero. El detalle técnico de cada función está en `DESARROLLO.md`.

## 2.1 — 8 de noviembre de 2026

**Nuevo**
- Cuando termina de cantarse una línea y siguen 5 segundos o más sin voz, la letra desaparece y sale ♪ (minireproductor, tarjeta «Letra» y pantalla de letra). Es una estimación con el ritmo de cada canción y no se guarda en los `.lrc` ni se publica.

## 2.0 — 2 de noviembre de 2026

Primera versión final con letras. Salió de beta tras las pruebas del usuario.

**Nuevo**
- Fuente opcional NetEase Cloud Music, desactivada por defecto, como respaldo de LRCLIB («Fuentes de letras» en la barra lateral).
- Editor de letras en 3 pasos: texto, sincronizar con Espacio, guardar como `.lrc`.
- Publicación opcional en LRCLIB, con confirmación previa.
- `LEEME.txt` dentro del ZIP para instalar en otra PC.

**Corregido**
- Corregir el texto de una letra ya no borra lo sincronizado.
- −0,1 / +0,1 s actúan sobre la última línea marcada; se agregaron los atajos ←, →, ↑, ↓ y F2.
- Los botones del editor ya no salen cortados.
- Las líneas largas usan hasta 2 renglones en el minireproductor y en la tarjeta «Letra».
- Las casillas marcadas ya no parecen desmarcadas.

**Cambiado**
- Consultas a LRCLIB espaciadas 1,4 s y respetando sus pausas, según su documentación oficial.

## 2.0 beta — 1 de noviembre de 2026

Se desarrolla aparte de la 1.0, en su propia carpeta y con sus propios datos (`%APPDATA%\Sonora2`).

**Nuevo**
- Letras sincronizadas: línea actual resaltada, desplazamiento automático y clic para saltar a ese momento.
- Búsqueda de letras en archivo `.lrc`, etiquetas de la canción y LRCLIB, con caché.
- Tarjeta «Letra» en el panel derecho y línea actual en el minireproductor.
- Marcas de letra en la lista, orden por letra y sección «Sin letra».
- Revisión de letras en segundo plano, con reintentos automáticos si el servidor falla.

## 1.0 — 1 de noviembre de 2026

Primera versión. Se conserva congelada aparte, fuera de este repositorio.

**Nuevo**
- Reproducción de MP3, FLAC, WAV, OGG, OPUS, M4A/AAC, WMA, AIFF, ALAC, APE y más.
- Vistas de Canciones, Álbumes, Artistas, Carpetas y Cola, con búsqueda.
- Nueve formas de ordenar, en ambos sentidos; cada vista recuerda su orden.
- La interfaz toma el color de la carátula que suena.
- Minireproductor flotante.
- Botón «Actualizar biblioteca» (F5) y detección automática de cambios en las carpetas.
- Teclas multimedia y botones ⏮ ⏯ ⏭ en la barra de tareas.
- Programa `.exe` con ícono, acceso directo y ZIP para otra PC.

**Corregido**
- Primer escaneo de 1128 canciones: de 80 s a 6 s.
- Abrir, ordenar, buscar y cambiar de canción: varias veces más rápido.
- Los archivos de 0 bytes (descargas fallidas) ya no aparecen como canciones.
- Las preferencias pasaron del registro de Windows a un archivo `settings.ini`.
