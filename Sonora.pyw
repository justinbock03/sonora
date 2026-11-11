"""Sonora — reproductor de música.

Uso:  pythonw Sonora.pyw [archivos o carpetas...]
"""
import multiprocessing
import sys
from pathlib import Path

# Sólo importaciones livianas aquí arriba: los procesos auxiliares de la verificación de
# LRCLIB (sonora/pow.py) vuelven a cargar este archivo y no deben arrancar la interfaz.
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main():
    multiprocessing.freeze_support()  # en el .exe, los procesos auxiliares terminan aquí
    if len(sys.argv) == 3 and sys.argv[1] == "--prueba-verificacion":
        # Diagnóstico: resuelve un desafío local (sin internet) y escribe el resultado en un archivo.
        import time
        from sonora import pow
        target = "0000FF" + "00" * 29
        t0 = time.perf_counter()
        nonce = pow.solve("prueba-sonora", target)
        ok = nonce is not None and pow.verify("prueba-sonora", target, nonce)
        Path(sys.argv[2]).write_text(f"ok={ok} nonce={nonce} segundos={time.perf_counter() - t0:.2f}",
                                     encoding="utf-8")
        return
    import ctypes

    from PySide6.QtWidgets import QApplication

    from sonora.library import APP_DIR
    from sonora.theme import app_icon_pixmap, make_app_icon
    from sonora.ui import MainWindow

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Sonora.MusicPlayer.2")
    except Exception:
        pass
    app = QApplication(sys.argv)
    app.setApplicationName("Sonora")
    app.setStyle("Fusion")
    app.setWindowIcon(make_app_icon())
    ico = APP_DIR / "sonora.ico"
    if not ico.exists():
        app_icon_pixmap(256).save(str(ico), "ICO")
    win = MainWindow()
    win.setWindowIcon(app.windowIcon())
    win.show()
    if len(sys.argv) > 1:
        win.open_paths(sys.argv[1:])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
