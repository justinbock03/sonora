"""Colores, íconos y hoja de estilos de Sonora."""
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QLinearGradient, QPainter, QPixmap

ICON_FONT = "Segoe MDL2 Assets"
UI_FONT = "Segoe UI"

BG = "#08080b"
PANEL = "#121217"
SURFACE = "#1a1a21"
SURFACE_2 = "#24242d"
TEXT = "#f3f3f7"
MUTED = "#a1a1b3"
DIM = "#6c6c80"
DEFAULT_ACCENT = QColor("#8b5cf6")


class G:
    """Glifos de Segoe MDL2 Assets."""
    PLAY = ""
    PAUSE = ""
    PREV = ""
    NEXT = ""
    SHUFFLE = ""
    REPEAT_ALL = ""
    REPEAT_ONE = ""
    VOLUME = ""
    MUTE = ""
    MUSIC = ""
    NOTE = ""
    ALBUM = ""
    ARTIST = ""
    QUEUE = ""
    FOLDER = ""
    ADD = ""
    SEARCH = ""
    MINI = ""
    EXPAND = ""
    CLOSE = ""
    BACK = ""
    PANEL = ""
    SETTINGS = ""
    FILE = ""
    REFRESH = ""
    LYRICS = ""
    GLOBE = ""
    SORT_UP = ""
    SORT_DOWN = ""


def on_color(c: QColor) -> str:
    """Color de texto legible encima de `c`."""
    lum = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
    return "#0b0b0f" if lum > 150 else "#ffffff"


def dominant_color(img: QImage) -> QColor:
    """Color vivo predominante de una carátula (histograma de tonos)."""
    if img is None or img.isNull():
        return QColor(DEFAULT_ACCENT)
    small = img.scaled(28, 28, Qt.AspectRatioMode.IgnoreAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
    bins = [[0.0, 0.0, 0.0, 0.0] for _ in range(24)]  # peso, r, g, b
    for y in range(small.height()):
        for x in range(small.width()):
            c = small.pixelColor(x, y)
            h, s, v, _ = c.getHsvF()
            if h < 0 or s < 0.18 or v < 0.2:
                continue
            w = s * s * v
            b = bins[int(h * 24) % 24]
            b[0] += w
            b[1] += c.redF() * w
            b[2] += c.greenF() * w
            b[3] += c.blueF() * w
    best = max(bins, key=lambda b: b[0])
    if best[0] < 1.5:  # carátula casi en escala de grises
        return QColor(DEFAULT_ACCENT)
    c = QColor.fromRgbF(best[1] / best[0], best[2] / best[0], best[3] / best[0])
    h, s, v, _ = c.getHsvF()
    return QColor.fromHsvF(max(h, 0.0), min(max(s, 0.5), 0.85), min(max(v, 0.78), 0.95))


def glyph_pixmap(glyph: str, color, size: int, dpr: float = 2.0) -> QPixmap:
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    f = QFont(ICON_FONT)
    f.setPixelSize(int(size * 0.8))
    p.setFont(f)
    p.setPen(QColor(color))
    p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, glyph)
    p.end()
    return pm


def glyph_icon(glyph: str, color=MUTED, color_on=TEXT, size: int = 18) -> QIcon:
    icon = QIcon()
    off, on = glyph_pixmap(glyph, color, size), glyph_pixmap(glyph, color_on, size)
    icon.addPixmap(off, QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(on, QIcon.Mode.Active, QIcon.State.Off)
    icon.addPixmap(on, QIcon.Mode.Normal, QIcon.State.On)
    icon.addPixmap(on, QIcon.Mode.Active, QIcon.State.On)
    return icon


def app_icon_pixmap(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    g = QLinearGradient(0, 0, size, size)
    g.setColorAt(0, QColor("#8b5cf6"))
    g.setColorAt(1, QColor("#ec4899"))
    p.setBrush(g)
    p.setPen(Qt.PenStyle.NoPen)
    r = size * 0.24
    p.drawRoundedRect(QRectF(0, 0, size, size), r, r)
    f = QFont(ICON_FONT)
    f.setPixelSize(int(size * 0.56))
    p.setFont(f)
    p.setPen(QColor("white"))
    p.drawText(QRectF(0, size * 0.02, size, size), Qt.AlignmentFlag.AlignCenter, G.NOTE)
    p.end()
    return pm


def make_app_icon() -> QIcon:
    icon = QIcon()
    for s in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        icon.addPixmap(app_icon_pixmap(s))
    return icon


QSS = """
* { font-family: "Segoe UI"; }
QWidget { color: @TEXT@; font-size: 13px; }
QMainWindow, #root { background: @BG@; }
#panel { background: @PANEL@; border-radius: 12px; }
QToolTip { background: @SURFACE_2@; color: @TEXT@; border: 1px solid #33333f; padding: 5px 8px; }

#logo { font-size: 21px; font-weight: 800; }
#navButton { text-align: left; padding: 10px 14px; border: none; border-radius: 8px;
             color: @MUTED@; font-size: 14px; font-weight: 600; background: transparent; }
#navButton:hover { color: @TEXT@; background: @SURFACE@; }
#navButton:checked { color: @TEXT@; background: @SURFACE_2@; }
#sectionLabel { color: @DIM@; font-size: 11px; font-weight: 700; padding: 0 14px; }
#scanLabel { color: @MUTED@; font-size: 12px; padding: 0 14px; }

#pill { background: @SURFACE_2@; border: none; border-radius: 16px; padding: 0 18px;
        min-height: 34px; font-weight: 600; color: @TEXT@; }
#pill:hover { background: #30303b; }
#accentPill { background: @A@; color: @ON_A@; border: none; border-radius: 17px;
              padding: 0 20px; min-height: 34px; font-weight: 700; }
#accentPill:hover { background: @A_HOVER@; }

#search { background: rgba(0,0,0,0.35); border: 1px solid rgba(255,255,255,0.08);
          border-radius: 17px; padding: 0 12px; min-height: 34px; selection-background-color: @A@; }
#search:focus { border: 1px solid @A@; }
QComboBox#sort { background: rgba(0,0,0,0.35); border: 1px solid rgba(255,255,255,0.08);
                 border-radius: 17px; padding: 0 16px; min-height: 34px; min-width: 170px; }
QComboBox#sort::drop-down { border: none; width: 22px; }
QComboBox#sort::down-arrow { image: none; }
QComboBox QAbstractItemView { background: @SURFACE_2@; border: 1px solid #33333f; padding: 4px;
                              outline: 0; selection-background-color: @A_SOFT@; selection-color: @TEXT@; }

#kicker { color: @TEXT@; font-size: 12px; font-weight: 700; }
#bannerTitle { font-size: 46px; font-weight: 800; }
#bannerSub { color: rgba(255,255,255,0.72); font-size: 13px; }

#bigPlay { background: @A@; color: @ON_A@; border: none; border-radius: 28px;
           font-family: "Segoe MDL2 Assets"; font-size: 20px; }
#bigPlay:hover { background: @A_HOVER@; }
#iconBtn { background: transparent; border: none; color: @MUTED@; border-radius: 16px;
           font-family: "Segoe MDL2 Assets"; font-size: 15px; }
#iconBtn:hover { color: @TEXT@; background: rgba(255,255,255,0.07); }
#iconBtn[active="true"] { color: @A@; }
#playBtn { background: @TEXT@; color: @BG@; border: none; border-radius: 20px;
           font-family: "Segoe MDL2 Assets"; font-size: 16px; }
#playBtn:hover { background: #ffffff; }

#playerBar { background: @BG@; }
#nowTitle { font-size: 14px; font-weight: 600; }
#nowArtist, #time { color: @MUTED@; font-size: 12px; }
#panelKicker { font-size: 14px; font-weight: 700; }
#panelTitle { font-size: 22px; font-weight: 800; }
#panelArtist { color: @MUTED@; font-size: 14px; }
#panelAlbum { color: @DIM@; font-size: 12px; }
#panelHeading { font-size: 14px; font-weight: 700; }
#emptyTitle { font-size: 26px; font-weight: 800; }
#emptySub { color: @MUTED@; font-size: 14px; }

QSlider::groove:horizontal { height: 4px; background: rgba(255,255,255,0.18); border-radius: 2px; }
QSlider::sub-page:horizontal { background: @A@; border-radius: 2px; }
QSlider::handle:horizontal { background: #ffffff; width: 12px; height: 12px; margin: -4px 0;
                             border-radius: 6px; }

QScrollBar:vertical { background: transparent; width: 12px; margin: 4px 2px; }
QScrollBar::handle:vertical { background: rgba(255,255,255,0.16); border-radius: 4px; min-height: 40px; }
QScrollBar::handle:vertical:hover { background: rgba(255,255,255,0.30); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { height: 0; }

QListView { background: transparent; border: none; outline: 0; }
QMenu { background: @SURFACE_2@; border: 1px solid #33333f; padding: 6px; }
QMenu::item { padding: 7px 22px 7px 14px; border-radius: 6px; }
QMenu::item:selected { background: rgba(255,255,255,0.09); }
QMenu::separator { height: 1px; background: #33333f; margin: 4px 8px; }

QDialog { background: @PANEL@; }
QListWidget { background: @SURFACE@; border-radius: 8px; border: none; padding: 4px; outline: 0; }
QListWidget::item { padding: 8px; border-radius: 6px; }
QListWidget::item:selected { background: @A_SOFT@; color: @TEXT@; }

#versionBadge { color: @MUTED@; background: @SURFACE_2@; border-radius: 6px; padding: 1px 6px;
                font-size: 10px; font-weight: 700; }
#lyricsTitle { font-size: 20px; font-weight: 800; color: #ffffff; }
#lyricsArtist { font-size: 14px; color: rgba(255,255,255,0.75); }
#lyricsSource { font-size: 12px; color: rgba(255,255,255,0.6); padding-right: 6px; }
#lyricsBtn { background: transparent; border: none; color: rgba(255,255,255,0.75); border-radius: 17px;
             font-family: "Segoe MDL2 Assets"; font-size: 14px; }
#lyricsBtn:hover { background: rgba(255,255,255,0.14); color: #ffffff; }

#stepBtn { background: rgba(255,255,255,0.08); border: none; border-radius: 15px; padding: 0 16px;
           min-height: 30px; color: rgba(255,255,255,0.75); font-weight: 600; }
#stepBtn:hover { background: rgba(255,255,255,0.16); }
#stepBtn:checked { background: #ffffff; color: #0b0b0f; }
#editorHint { color: rgba(255,255,255,0.72); font-size: 13px; }
#editorStatus { font-size: 13px; font-weight: 600; }
QPlainTextEdit#lyricsEdit { background: rgba(0,0,0,0.28); border: 1px solid rgba(255,255,255,0.10);
                            border-radius: 10px; padding: 10px; font-size: 15px; color: #ffffff;
                            selection-background-color: rgba(255,255,255,0.3); }
QListWidget#syncList { background: rgba(0,0,0,0.28); border: 1px solid rgba(255,255,255,0.10);
                       border-radius: 10px; padding: 6px; font-size: 15px; }
QListWidget#syncList::item { padding: 6px 8px; border-radius: 6px; }
QListWidget#syncList::item:selected { background: rgba(255,255,255,0.14); }
QLineEdit#editorField { background: rgba(0,0,0,0.28); border: 1px solid rgba(255,255,255,0.12);
                        border-radius: 8px; padding: 6px 10px; color: #ffffff; }
QLineEdit#editorField:focus { border: 1px solid rgba(255,255,255,0.45); }
QCheckBox { color: #ffffff; spacing: 8px; font-weight: 600; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 5px;
                       border: 1px solid rgba(255,255,255,0.55); background: rgba(0,0,0,0.25); }
QCheckBox::indicator:checked { background: @A@; border: 3px solid #ffffff; }
QCheckBox::indicator:checked:disabled { background: @A@; border: 3px solid rgba(255,255,255,0.6); }
QCheckBox:disabled { color: rgba(255,255,255,0.85); }
QMessageBox { background: @PANEL@; }
QMessageBox QLabel { color: @TEXT@; font-size: 13px; }
QMessageBox QPushButton { background: @SURFACE_2@; color: @TEXT@; border: none; border-radius: 6px;
                          padding: 6px 18px; min-width: 80px; }
QMessageBox QPushButton:hover { background: #30303b; }
QInputDialog QLineEdit { background: @SURFACE_2@; color: @TEXT@; border: 1px solid #3a3a48; border-radius: 6px;
                         padding: 6px 8px; min-width: 420px; font-size: 14px; }
QInputDialog QPushButton { background: @SURFACE_2@; color: @TEXT@; border: none; border-radius: 6px;
                           padding: 6px 18px; min-width: 80px; }
QInputDialog QPushButton:hover { background: #30303b; }
#lyricsPill { background: rgba(255,255,255,0.12); border: none; border-radius: 15px; padding: 0 14px;
              min-height: 30px; color: #ffffff; font-weight: 600; }
#lyricsPill:hover { background: rgba(255,255,255,0.22); }

#miniTitle { font-size: 15px; font-weight: 700; color: #ffffff; }
#miniLyric { font-size: 13px; font-weight: 700; color: #ffffff; }
#miniSmall[active="true"] { color: #ffffff; background: rgba(255,255,255,0.12); }
#miniArtist { font-size: 12px; color: rgba(255,255,255,0.72); }
#miniBtn { background: transparent; border: none; color: #ffffff; border-radius: 15px;
           font-family: "Segoe MDL2 Assets"; font-size: 14px; }
#miniBtn:hover { background: rgba(255,255,255,0.14); }
#miniBtn[active="false"] { color: rgba(255,255,255,0.5); }
#miniBtn[active="true"] { color: @A_LIGHT@; }
#miniSmall { background: transparent; border: none; color: rgba(255,255,255,0.6); border-radius: 12px;
             font-family: "Segoe MDL2 Assets"; font-size: 10px; }
#miniSmall:hover { background: rgba(255,255,255,0.14); color: #ffffff; }
#miniPlay { background: #ffffff; color: #0b0b0f; border: none; border-radius: 19px;
            font-family: "Segoe MDL2 Assets"; font-size: 15px; }
#miniPlay:hover { background: @A_LIGHT@; }
"""


# Sólo las reglas que dependen del color de la canción; se aplican a unos pocos widgets
# (cabecera, barra del reproductor y minireproductor) para no re-estilizar toda la app.
ACCENT_QSS = """
#bigPlay { background: @A@; color: @ON_A@; }
#bigPlay:hover { background: @A_HOVER@; }
#iconBtn[active="true"] { color: @A@; }
QSlider::sub-page:horizontal { background: @A@; border-radius: 2px; }
#miniBtn[active="true"] { color: @A_LIGHT@; }
#miniPlay:hover { background: @A_LIGHT@; }
#miniLyric { color: @A_LIGHT@; }
#accentPill { background: @A@; color: @ON_A@; }
#accentPill:hover { background: @A_HOVER@; }
"""


def accent_qss(accent: QColor) -> str:
    return build_qss(accent, ACCENT_QSS)


def build_qss(accent: QColor, template: str = QSS) -> str:
    tokens = {
        "@A_SOFT@": f"rgba({accent.red()},{accent.green()},{accent.blue()},0.22)",
        "@A_HOVER@": accent.lighter(112).name(),
        "@A_LIGHT@": accent.lighter(135).name(),
        "@ON_A@": on_color(accent),
        "@A@": accent.name(),
        "@BG@": BG, "@PANEL@": PANEL, "@SURFACE_2@": SURFACE_2, "@SURFACE@": SURFACE,
        "@TEXT@": TEXT, "@MUTED@": MUTED, "@DIM@": DIM,
    }
    qss = template
    for k, v in tokens.items():
        qss = qss.replace(k, v)
    return qss
