# Reconstruye dist\Sonora\Sonora.exe y el ZIP portÃ¡til.
# Uso (desde la carpeta Sonora):  powershell -ExecutionPolicy Bypass -File tools\build.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

python tools\make_icon.py
pyinstaller --noconfirm --clean --windowed --name Sonora `
  --icon "$root\assets\sonora.ico" --distpath dist --workpath build --specpath build `
  --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets `
  --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick --exclude-module PySide6.QtPdf `
  --exclude-module tkinter Sonora.pyw
if ($LASTEXITCODE -ne 0) { throw "PyInstaller fallÃ³" }

Copy-Item "tools\Crear acceso directo.bat" "dist\Sonora\"
Copy-Item "tools\LEEME.txt" "dist\Sonora\LEEME.txt"
Compress-Archive -Path "dist\Sonora" -DestinationPath "dist\Sonora-2.1-portable.zip" -Force
Write-Host "Listo: dist\Sonora\Sonora.exe y dist\Sonora-2.1-portable.zip"
