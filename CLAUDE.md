# Sonora 2.x

Antes de cambiar nada, lee `DESARROLLO.md` (estado, arquitectura, decisiones, cómo compilar y
cómo probar) y `HISTORIAL.md` (cambios por versión).

Reglas rápidas:
- **El repositorio es público**: no escribir en él rutas de la PC del desarrollador, nombres de su
  música, correos ni otros datos personales. Esa información está en la memoria local de Claude.
- Sonora 1.0 vive en otra carpeta y está congelada: no se edita ni se recompila.
- Tras cambiar código, recompilar con `tools\build.ps1`; si `Sonora.exe` está abierto, compilar en
  `build\staging` y pedir que lo cierren.
- En pruebas: APPDATA aislado, volumen 0, nunca publicar de verdad en LRCLIB, nunca escribir `.lrc`
  en la música real.
- Al terminar cualquier cambio: anotarlo en `HISTORIAL.md` y `DESARROLLO.md`, commit y `git push`.
  Cada versión lleva etiqueta (`vX.Y`, también subida) y un GitHub Release con el ZIP portátil
  (`gh release create vX.Y dist\Sonora-X.Y-portable.zip`). El desarrollador no usa Git: se encarga Claude.
