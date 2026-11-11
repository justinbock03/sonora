# Sonora — documento principal de desarrollo

Reproductor de música de escritorio para Windows, con diseño oscuro tipo Spotify, minireproductor
flotante y letras sincronizadas. Escrito en **Python 3.14 + PySide6 (Qt 6)**; el audio lo decodifica
**FFmpeg** a través de QtMultimedia y los metadatos se leen con **mutagen**.

Este documento resume todo lo construido, corregido y decidido hasta el **10 de noviembre de 2026**,
para poder retomar el desarrollo sin depender del historial de la conversación. Los cambios por
versión y fecha están en `HISTORIAL.md`.

> El repositorio es **público**: aquí no van rutas de la PC del desarrollador, nombres de su música
> ni datos personales. Esa información vive sólo en la configuración local de quien desarrolla.

---

## 1. Versiones y ubicaciones

| | **Sonora 1.0** (congelada) | **Sonora 2.x** (actual: 2.1) |
|---|---|---|
| Código | Carpeta aparte, fuera de este repositorio | Este repositorio |
| Programa | `dist\Sonora\Sonora.exe` | `dist\Sonora\Sonora.exe` |
| Acceso directo | «Sonora» (Escritorio y menú Inicio) | «Sonora 2» |
| Datos | `%APPDATA%\Sonora` | `%APPDATA%\Sonora2` |
| ZIP portátil | `dist\Sonora-portable.zip` | `dist\Sonora-X.Y-portable.zip` (incluye `LEEME.txt`; se conservan los anteriores) |

La 2.0 salió de beta el 2 de noviembre de 2026. Cada cambio visible sube la versión 2.x
(`APP_VERSION` en `library.py`, título de `tools\LEEME.txt` y nombre del ZIP en `tools\build.ps1`).

- **La 1.0 no se modifica**: se conserva como recuerdo de la primera versión. Todo desarrollo nuevo va aquí.
- **Git**: cada cambio es un commit y cada versión una etiqueta (`v2.1`). La historia empieza en la 2.1.
- **GitHub** (repositorio **público**): https://github.com/justinbock03/sonora. Tras cada commit: `git push` (y `git push origin vX.Y` al crear una versión).
- **Distribución**: cada versión se publica como *GitHub Release* con el ZIP portátil adjunto (https://github.com/justinbock03/sonora/releases). Cualquiera puede descargarla sin cuenta.
- La 2.0, la primera vez que se abre, **copia** biblioteca, carátulas y preferencias de la 1.0 si existen (nunca escribe en los datos de la 1.0).
- Instalar en otra PC: descargar el ZIP, descomprimir en un lugar fijo y ejecutar `Crear acceso directo.bat` (no necesita Python). Cada PC tiene su propia biblioteca.

## 2. Ejecutar, compilar y diagnosticar

```powershell
# Ejecutar desde el código (desarrollo)
pythonw Sonora.pyw            # opcional: rutas de archivos o carpetas para abrir y reproducir

# Generar el .exe y el ZIP portátil (desde la carpeta Sonora2)
powershell -ExecutionPolicy Bypass -File tools\build.ps1

# Diagnóstico de la verificación de LRCLIB dentro del .exe (sin internet)
Sonora.exe --prueba-verificacion C:\ruta\resultado.txt
```

- `tools\build.ps1`: regenera el ícono (`tools\make_icon.py`), compila con PyInstaller (excluye WebEngine/QML/PDF) y crea el ZIP.
- **Si Sonora.exe está abierto, no se puede reemplazar**: compilar en `build\staging` y cambiar la carpeta cuando el usuario lo cierre.
- Dependencias: `pip install PySide6 mutagen pyinstaller`.

## 3. Arquitectura (carpeta `sonora/`)

| Módulo | Responsabilidad |
|---|---|
| `library.py` | Biblioteca: lectura de metadatos y carátulas, escaneo en segundo plano (`Scanner`), agrupación en álbumes/artistas/carpetas, orden natural, migración desde la 1.0. |
| `player.py` | Motor de reproducción sobre `QMediaPlayer`: cola, aleatorio, repetición, volumen perceptual. |
| `ui.py` | Ventana principal: modelos y delegados de las listas, páginas, cabecera, panel derecho, barra del reproductor, navegación, ajustes, revisión de letras, editor y publicación. |
| `mini.py` | Minireproductor flotante. |
| `widgets.py` | Widgets comunes (`ElidedLabel`, `WrapLabel`, `ClickSlider`), caché de carátulas, integración con Windows (barra de título oscura, teclas multimedia, botones de la miniatura de la barra de tareas). |
| `theme.py` | Colores, glifos (Segoe MDL2 Assets), hoja de estilos, color dominante de la carátula, ícono de la app. |
| `lyrics.py` | Letras: búsqueda (archivo .lrc → letra del usuario → etiquetas → caché → LRCLIB → NetEase opcional), caché, estado por canción, revisión en segundo plano, guardado de letras del usuario y publicación en LRCLIB. |
| `lyrics_view.py` | Pantalla de letra sincronizada y tarjeta «Letra» del panel derecho. |
| `lyrics_editor.py` | Editor de letras en 3 pasos (Texto, Sincronizar, Guardar). |
| `lyrics_netease.py` | Fuente opcional NetEase Cloud Music (API web no oficial). |
| `pow.py` | Verificación *proof-of-work* que exige LRCLIB para publicar; se reparte en varios procesos. Sin Qt a propósito. |

## 4. Funciones

### 4.1 Sonora 1.0
- **Formatos**: MP3, FLAC, WAV, OGG, OPUS, M4A/AAC, WMA, AIFF, ALAC, APE y más (FFmpeg).
- **Biblioteca**: escaneo de carpetas en un hilo aparte; sólo relee archivos nuevos o modificados; carátulas incrustadas o de la carpeta (`cover.jpg`, `folder.jpg`…); ignora archivos de 0 bytes.
- **Vistas**: Canciones, Álbumes, Artistas, Carpetas y Cola, con búsqueda.
- **Orden**: agregadas recientemente, título, artista, álbum, año, duración, número de pista, nombre de archivo y fecha del archivo; ascendente/descendente; clic en los encabezados de columna; orden «natural» (2 antes que 10, sin importar tildes). Cada vista (biblioteca, álbum, artista, carpeta) **recuerda su propio orden**.
- **Interfaz**: panel «Reproduciendo ahora» con «A continuación»; la interfaz toma el **color dominante de la carátula**; ecualizador animado en la fila que suena.
- **Minireproductor**: siempre visible, fondo con la carátula difuminada, se arrastra, rueda = volumen, clic en la barra = saltar, doble clic = abrir la ventana principal.
- **Actualizar biblioteca** (botón o F5) y **vigilancia automática** de las carpetas, con aviso «✓ N nuevas · N eliminadas».
- **Teclas multimedia globales** (Play/Pausa, Siguiente, Anterior, Stop).
- **Botones en la miniatura de la barra de tareas** (Anterior, Reproducir/Pausa, Siguiente), también en el minireproductor.
- **Atajos**: Espacio, Ctrl+←/→, Ctrl+↑/↓ (volumen), Ctrl+F, Ctrl+M (minireproductor), F5.
- Arrastrar y soltar archivos/carpetas, abrir por línea de comandos, recordar volumen, modos, última canción y posición.
- Empaquetado como `.exe` con ícono propio, acceso directo y ZIP portátil.

### 4.2 Sonora 2.0
- **Letras** (botón 🎤 o Ctrl+L): pantalla con la línea actual resaltada, desplazamiento automático, clic en una línea para saltar a ese momento, pausa del seguimiento 4 s al usar la rueda, bordes desvanecidos, fondo con el color de la canción.
- **Muestra de la letra**: tarjeta «Letra» en el panel derecho (línea actual en hasta 2 renglones + siguientes) y línea actual en el minireproductor (hasta 2 renglones; se activa con su botón 🎤).
- **Marcas de letra en la lista**: 🎤 de color = sincronizada, 🎤 gris = sólo texto, ♪ = instrumental, «–» = sin letra, punto = sin revisar o pendiente. Orden por «Letra». Sección **«Sin letra (N)»** en la barra lateral.
- **Revisión en segundo plano** de toda la biblioteca: primero las próximas de la cola; reintentos automáticos con esperas crecientes (30 s → 10 min) si el servidor falla; el progreso se guarda; las «sin letra» se reconsultan cada 7 días; clic derecho → «Buscar la letra de nuevo».
- **Editor de letras** (botón «Agregar/Sincronizar/Editar letra» o clic derecho → «Agregar o editar letra…»):
  1. *Texto*: pegar/escribir (acepta .lrc con tiempos), o marcar como instrumental, o guardar sin sincronizar.
  2. *Sincronizar*: Espacio marca cada línea; ←/→ ±0,1 s a la línea seleccionada (tras marcar, la última marcada); ↑/↓ cambian de línea; F2 corrige el texto de una línea; Retroceso deshace; doble clic escucha desde la línea; la línea que suena se ilumina para comprobar.
  3. *Guardar*: `.lrc` junto a la canción (o en los datos de Sonora si la carpeta no lo permite) y, opcionalmente, **publicar en LRCLIB** tras una confirmación que muestra exactamente qué se envía.
- **Fuentes de letras** (barra lateral): LRCLIB siempre; **NetEase Cloud Music opcional y desactivado por defecto**, como respaldo.
- Insignia de versión «2.0» y carpeta de datos propia.

### 4.3 Sonora 2.1
- **♪ en los tramos instrumentales**: cuando termina de cantarse una línea y siguen 5 s o más sin voz, la letra desaparece y se muestra ♪ en el minireproductor, la tarjeta «Letra» y la pantalla de letra. El LRC sólo indica cuándo *empieza* cada línea, así que `lyrics.with_music_breaks()` estima su final con el ritmo de la canción (mediana de ms por letra). Es una copia sólo para mostrar: el editor, la caché y lo publicado usan la letra original. Con un umbral de 3 s salían falsos positivos en notas alargadas; por eso 5 s.

## 5. Correcciones importantes

| Problema | Causa | Solución |
|---|---|---|
| Error al arrancar: `positionChanged(qlonglong)` | Señales de Qt de 64 bits | Señales declaradas como `"qlonglong"`. |
| Botones «píldora» con esquinas cuadradas | Radio mayor que la mitad de la altura | Alturas mínimas y radios ajustados. |
| Primer escaneo de 1128 canciones en 80 s | Se re-codificaba cada carátula | Las carátulas JPEG se copian tal cual: **6 s**. |
| Abrir carpeta 905 ms, ordenar/buscar 300+ ms | `QSortFilterProxyModel` comparaba en Python de dos en dos | Filtro y orden en una pasada con `sorted()`: 25–115 ms; búsqueda 1–15 ms (con espera de 140 ms al teclear). |
| Cambio de canción 240–460 ms | Se re-aplicaba la hoja de estilos de toda la app | Sólo se re-estilizan los widgets que usan el color: 17–37 ms. |
| Ecualizador: 40 ms × 11 veces/s | Repintaba toda la lista | Repinta sólo la fila que suena: ~8 ms. |
| Las pruebas leían/escribían las preferencias reales | `QSettings` usaba el registro de Windows | Preferencias en `settings.ini` dentro de la carpeta de datos (se migró lo del registro). |
| Botones de la barra de tareas sin efecto | Qt no pasa los `WM_COMMAND` *enviados* a los filtros nativos | Subclasificación de la ventana con `SetWindowSubclass`. |
| Canciones de 0:00 sin artista ni carátula | Archivos de 0 bytes (descargas fallidas) | Se ignoran al escanear. |
| Letra resaltada de la canción anterior al cambiar | Se usaba la posición antigua del reproductor | Se usa 0 (o la posición a restaurar). |
| «Solo encuentra letras en inglés» | Eran errores 503 de LRCLIB, no el idioma | Medido: en español encontró 18 de 19 consultas respondidas. Reintentos y respaldo. |
| Corregir el texto en el editor borraba la sincronización | Los tiempos se reiniciaban si cambiaba el texto | Alineación por diferencias y parecido de líneas: sólo las líneas nuevas quedan sin marcar. |
| −0,1/+0,1 s afectaban la línea sombreada, no la recién marcada | La selección no seguía a la marca | Al marcar, la selección pasa a esa línea; atajos ←/→/↑/↓/F2. |
| Botones del editor cortados en ventanas angostas | Una sola fila de botones | Dos filas. |
| Línea de letra cortada con «…» en el minireproductor | Una sola línea | Hasta 2 renglones (`WrapLabel`). |

## 6. Decisiones técnicas (y por qué)

- **PySide6 + FFmpeg** en vez de reescribir en C++/Rust: como en Spotify o Apple Music, el audio ya se decodifica en código nativo; Python sólo maneja la interfaz. Reescribir sólo ahorraría ~0,5 s al arrancar.
- **LyricFind/Musixmatch no son viables**: requieren contrato comercial. Genius y Letras.com no tienen API de letras. **LRCLIB** es la única fuente gratuita, abierta y con letras sincronizadas.
- **Reglas de LRCLIB** (documentación oficial): una consulta a la vez, ~45/min para clientes no registrados, respetar `Retry-After` con hasta 30 % de variación. Sonora espacia las consultas **1,4 s**. No se usan consultas en paralelo aunque la revisión inicial tarde (≈1–2 h para ~1100 canciones) porque LRCLIB es un servicio de voluntarios y ya está saturado.
- **Publicar en LRCLIB**: `POST /api/request-challenge` → resolver SHA-256(prefijo + nonce) ≤ objetivo (como LRCGET) → `POST /api/publish` con `X-Publish-Token: prefijo:nonce`. En un núcleo tardaba ~1 min; con 7 procesos, **10–30 s** y sin congelar la interfaz. Por eso `Sonora.pyw` llama a `multiprocessing.freeze_support()` y sólo importa Qt dentro de `main()`.
- **NetEase como opción, no por defecto**: en las canciones de la biblioteca de prueba que LRCLIB no tiene, aportó sólo 1 de 12; pero tiene 13 de 15 canciones al azar, todas sincronizadas, así que es útil **como respaldo cuando LRCLIB no responde**. Su API es no oficial (un buscador ya mostró bloqueo antibots, código 406), así que se usa `cloudsearch`, con 1,2 s entre consultas, exigiendo coincidencia de artista y duración (±4 s) y filtrando líneas de créditos (作词/作曲, «edit by…»).
- **Teclas multimedia globales**: mientras Sonora está abierto, otras apps (p. ej. YouTube en el navegador) no reciben esas teclas.
- **Archivos `.lrc` junto a la canción**: así también los usan otros reproductores. Escribirlos dispara la vigilancia de carpetas; la vista de letra/editor está protegida para no cambiar de pantalla por eso.

## 7. Datos en disco (`%APPDATA%\Sonora2`)

| Archivo/carpeta | Contenido |
|---|---|
| `library.json` | Carpetas y canciones con metadatos. |
| `settings.ini` | Preferencias: geometría, volumen, modos, órdenes por vista, posición y modo del minireproductor, última canción, `netease`. |
| `covers\` | Carátulas (nombre = md5 de álbum o ruta). |
| `lyrics\*.json` | Caché de letras de internet (o «no encontrada» con fecha y fuentes probadas). |
| `lyrics\status.json` | Estado de letra por canción (para marcas y «Sin letra»). |
| `lyrics\user\` | Letras del usuario cuando no se pudo escribir el `.lrc` junto a la canción, o instrumentales. |

## 8. Cómo probar sin afectar al usuario

- Usar un `APPDATA` aislado (variable de entorno) y **volumen 0** en `settings.ini` de prueba.
- **Nunca publicar de verdad en LRCLIB** en pruebas: reemplazar `lyrics._post` por un simulador que valide el token con `pow.verify` y responda 201.
- No escribir `.lrc` en la carpeta de música real: copiar una canción a una carpeta temporal.
- Si una ventana de prueba queda en primer plano donde está el ratón, el resaltado de «hover» puede confundirse con la línea actual.
- `os._exit()` descarta la salida en búfer: usar `PYTHONUNBUFFERED=1` o `print(..., flush=True)`.
- Para medir rendimiento y cobertura de letras, usar una biblioteca real de ~1000 canciones (su ruta está en la configuración local del desarrollador, no aquí).

## 9. Problemas conocidos

- LRCLIB responde a menudo «servidor ocupado» (503) y a veces tarda 12 s: la primera revisión de letras es lenta.
- NetEase puede dejar de funcionar sin aviso (API no oficial).
- Ninguna fuente tiene grabaciones en vivo o artistas muy poco conocidos: para esas está el editor.
- El primer arranque compite con el escaneo inicial (~1 s más lento las primeras operaciones).

## 10. Pendientes e ideas

- [ ] Primera **publicación real** en LRCLIB hecha por el usuario y comprobada en lrclib.net.
- [ ] Identificar la app ante LRCLIB con un correo o sitio web en el `User-Agent` (lo piden; el usuario aún no dio un contacto).
- [ ] Ideas aplazadas por el usuario: precarga de la siguiente canción (sin silencios), normalización de volumen (ReplayGain/loudness) y fundido entre canciones.
- [ ] Posible ventana de **Configuración** general que reúna fuentes de letras, teclas multimedia y otras opciones.
