@echo off
rem Crea un acceso directo a Sonora 2 en el Escritorio y en el menu Inicio.
rem Debe estar en la misma carpeta que Sonora.exe.
set "EXE=%~dp0Sonora.exe"
if not exist "%EXE%" (
  echo No encuentro Sonora.exe junto a este archivo.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$exe = $env:EXE;" ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "foreach ($dir in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {" ^
  "  $lnk = $ws.CreateShortcut((Join-Path $dir 'Sonora 2.lnk'));" ^
  "  $lnk.TargetPath = $exe;" ^
  "  $lnk.WorkingDirectory = Split-Path $exe;" ^
  "  $lnk.IconLocation = $exe + ',0';" ^
  "  $lnk.Description = 'Sonora 2 - reproductor de musica';" ^
  "  $lnk.Save() }"
echo Listo: Sonora 2 ya esta en tu Escritorio y en el menu Inicio.
ping -n 4 127.0.0.1 >nul
