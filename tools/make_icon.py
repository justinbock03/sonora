"""Genera assets/sonora.ico con varios tamaños (PNG dentro de ICO)."""
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from sonora.theme import app_icon_pixmap  # noqa: E402

SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)


def png_bytes(size: int) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    app_icon_pixmap(size).save(buf, "PNG")
    return bytes(buf.data())


def main():
    app = QApplication([])  # noqa: F841 (necesario para dibujar con fuentes)
    images = [png_bytes(s) for s in SIZES]
    header = struct.pack("<HHH", 0, 1, len(SIZES))
    offset = 6 + 16 * len(SIZES)
    entries = b""
    for size, data in zip(SIZES, images):
        dim = 0 if size >= 256 else size  # 0 significa 256 en el formato ICO
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    out = ROOT / "assets" / "sonora.ico"
    out.parent.mkdir(exist_ok=True)
    out.write_bytes(header + entries + b"".join(images))
    print("ícono:", out)


if __name__ == "__main__":
    main()
