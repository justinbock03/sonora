"""Ventana principal de Sonora."""
import json
import math
import os
import random
import subprocess

from PySide6.QtCore import (QAbstractListModel, QFileSystemWatcher, QModelIndex, QPoint, QRect,
                            QRectF, QSettings, QSize, QSortFilterProxyModel, QStandardPaths, Qt, QTimer, Signal)
from PySide6.QtGui import (QAction, QColor, QFont, QGuiApplication, QKeySequence, QLinearGradient,
                           QPainter, QPainterPath, QPen, QShortcut)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog,
                               QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListView,
                               QListWidget, QMainWindow, QMenu, QMessageBox, QPushButton,
                               QStackedWidget, QStyle,
                               QStyledItemDelegate, QToolTip, QVBoxLayout, QWidget)

from .library import (APP_DIR, APP_VERSION, AUDIO_EXTS, Library, Scanner, group_albums, group_artists, group_folders,
                      is_audio, natural, read_track)
from .mini import MiniPlayer
from . import lyrics as lyrics_mod
from .lyrics import (ERROR, INSTRUMENTAL, NONE, PLAIN, SYNCED, LyricsService, Publisher, load_local,
                     with_music_breaks)
from .lyrics_editor import LyricsEditor
from .lyrics_view import LEAD_MS, LyricsCard, LyricsPage
from .player import REPEAT_OFF, REPEAT_ONE, Player
from .theme import (DEFAULT_ACCENT, DIM, G, ICON_FONT, MUTED, PANEL, TEXT, UI_FONT, accent_qss,
                    build_qss, dominant_color, glyph_icon)
from .widgets import (ClickSlider, Covers, ElidedLabel, MediaKeys, TaskbarButtons, dark_title_bar,
                      fmt_time,
                      fmt_total, icon_button, load_image_small, set_active)

TRACK_ROLE = Qt.ItemDataRole.UserRole + 1
ITEM_ROLE = Qt.ItemDataRole.UserRole + 2

SORTS = [("Agregadas recientemente", "added"), ("Título", "title"), ("Artista", "artist"),
         ("Álbum", "album"), ("Año", "year"), ("Duración", "duration"),
         ("Número de pista", "track"), ("Nombre de archivo", "filename"),
         ("Fecha del archivo", "mtime"), ("Letra", "lyrics")]
SORT_MODES = {m for _, m in SORTS}
DESC_BY_DEFAULT = {"added", "mtime"}
# Orden inicial de cada contexto; el que elija el usuario se recuerda por contexto.
DEFAULT_SORTS = {"library": ("added", True), "album": ("track", False),
                 "artist": ("year", False), "folder": ("filename", False),
                 "nolyrics": ("title", False)}
# Orden de «Letra»: primero las sincronizadas, al final las pendientes de revisar.
LYRICS_RANK = {SYNCED: 0, PLAIN: 1, INSTRUMENTAL: 2, NONE: 3, ERROR: 4, None: 5}
LYRICS_TIPS = {SYNCED: "Letra sincronizada", PLAIN: "Letra sin sincronizar", INSTRUMENTAL: "Instrumental",
               NONE: "Sin letra", ERROR: "Letra pendiente: el servidor no respondió, se reintentará sola",
               None: "Letra aún sin revisar"}


def open_settings() -> QSettings:
    """Preferencias en %APPDATA%\\Sonora\\settings.ini (junto a la biblioteca).

    Versiones anteriores usaban el registro; sus valores se copian la primera vez.
    """
    path = APP_DIR / "settings.ini"
    settings = QSettings(str(path), QSettings.Format.IniFormat)
    if not path.exists():
        old = QSettings("Sonora", "Sonora")
        for key in old.allKeys():
            settings.setValue(key, old.value(key))
        settings.sync()
    return settings


class State:
    """Estado compartido que leen los delegados al pintar."""

    def __init__(self):
        self.current_path = ""
        self.playing = False
        self.phase = 0.0
        self.accent = QColor(DEFAULT_ACCENT)
        self.lyrics_status = lambda path: None   # lo reemplaza la ventana principal


def ui_font(px: int, weight=QFont.Weight.Normal) -> QFont:
    f = QFont(UI_FONT)
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


# ================================================================ modelos

class TrackModel(QAbstractListModel):
    def __init__(self):
        super().__init__()
        self.tracks = []
        self._rows = None

    def set_tracks(self, tracks):
        self.beginResetModel()
        self.tracks = list(tracks)
        self._rows = None
        self.endResetModel()

    def row_of(self, path: str):
        if self._rows is None:
            self._rows = {t.path: i for i, t in enumerate(self.tracks)}
        return self._rows.get(path)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.tracks)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        t = self.tracks[index.row()]
        if role == TRACK_ROLE:
            return t
        if role == Qt.ItemDataRole.DisplayRole:
            return t.title
        return None


class SongsModel(TrackModel):
    """Canciones filtradas y ordenadas en una sola pasada con sorted().

    Mucho más rápido que QSortFilterProxyModel, que llama a Python por cada comparación.
    """

    def __init__(self):
        super().__init__()
        self.source = []
        self.text = ""
        self.scope = None   # None | ("album", clave) | ("artist", nombre) | ("folder", ruta) | ("nolyrics", None)
        self.mode = "added"
        self.desc = True
        self.lyrics_status = lambda path: None

    def set_source(self, tracks):
        self.source = list(tracks)
        self._rebuild()

    def configure(self, text=None, scope=False, mode=None, desc=None):
        if text is not None:
            self.text = text.lower().strip()
        if scope is not False:
            self.scope = scope
        if mode is not None:
            self.mode = mode
        if desc is not None:
            self.desc = desc
        self._rebuild()

    def _rebuild(self):
        items = self.source
        if self.scope is not None:
            kind, key = self.scope
            if kind == "album":
                items = [t for t in items if t.album_key == key]
            elif kind == "artist":
                k = key.lower()
                items = [t for t in items if k in (a.lower() for a in t.artists)]
            elif kind == "folder":
                items = [t for t in items if os.path.dirname(t.path) == key]
            elif kind == "nolyrics":
                items = [t for t in items if self.lyrics_status(t.path) == NONE]
        if self.text:
            items = [t for t in items if t.matches(self.text)]
        self.set_tracks(sorted(items, key=self._key, reverse=self.desc))

    def _key(self, t):
        m, n = self.mode, natural
        if m == "added":
            return (t.added, n(t.title))
        if m == "title":
            return (n(t.title), n(t.artist))
        if m == "artist":
            return (n(t.artist), n(t.album), t.disc_no, t.track_no, n(t.title))
        if m == "album":
            return (n(t.album), t.disc_no, t.track_no, n(t.title))
        if m == "year":
            return (t.year, n(t.album), t.disc_no, t.track_no)
        if m == "duration":
            return (t.duration, n(t.title))
        if m == "filename":
            return (n(os.path.basename(t.path)),)
        if m == "mtime":
            return (t.mtime, n(t.title))
        if m == "lyrics":
            return (LYRICS_RANK.get(self.lyrics_status(t.path), 5), n(t.title))
        return (n(t.album), t.disc_no, t.track_no, n(t.title))  # track

    def visible_tracks(self):
        return list(self.tracks)


class GridModel(QAbstractListModel):
    def __init__(self):
        super().__init__()
        self.items = []

    def set_items(self, items):
        self.beginResetModel()
        self.items = list(items)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        it = self.items[index.row()]
        if role == ITEM_ROLE:
            return it
        if role == Qt.ItemDataRole.DisplayRole:
            return f"{it.name} {it.subtitle}"
        return None


# ================================================================ delegados

def track_columns(left: int, width: int) -> dict:
    x = left + 12
    cols = {"num": (x, 28)}
    x += 28 + 10
    cols["cover"] = (x, 42)
    x += 42 + 14
    right = left + width - 14
    dur_w, lyr_w = 56, 28
    avail = right - dur_w - lyr_w - x
    year_w = 64 if avail > 560 else 0
    show_album = avail > 380
    title_w = int((avail - year_w) * (0.55 if show_album else 1.0))
    cols["title"] = (x, title_w - 16)
    cols["album"] = (x + title_w, avail - year_w - title_w - 16) if show_album else None
    cols["year"] = (right - dur_w - lyr_w - year_w, year_w) if year_w else None
    cols["lyr"] = (right - dur_w - lyr_w, lyr_w)
    cols["dur"] = (right - dur_w, dur_w)
    return cols


def draw_lyrics_mark(p: QPainter, rect: QRect, status, accent: QColor):
    """Indicador de letra: micrófono de color (sincronizada), gris (texto), «–» (sin letra)."""
    if status in (SYNCED, PLAIN):
        f = QFont(ICON_FONT)
        f.setPixelSize(13)
        p.setFont(f)
        p.setPen(accent.lighter(130) if status == SYNCED else QColor(MUTED))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, G.LYRICS)
    elif status == INSTRUMENTAL:
        p.setFont(ui_font(13))
        p.setPen(QColor(MUTED))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "♪")
    elif status == NONE:
        p.setFont(ui_font(13))
        p.setPen(QColor(DIM))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "–")
    else:  # sin revisar o pendiente por error del servidor
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 45))
        c = rect.center()
        p.drawEllipse(QRectF(c.x() - 2, c.y() - 2, 4, 4))


def draw_eq(p: QPainter, rect: QRect, color: QColor, phase: float, animate: bool):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    w, gap = 3, 3
    x0 = rect.center().x() - (3 * w + 2 * gap) / 2
    for i in range(3):
        h = (0.35 + 0.65 * abs(math.sin(phase * (1.3 + i * 0.4) + i * 1.7))) if animate else 0.45
        bh = rect.height() * h
        p.drawRoundedRect(QRectF(x0 + i * (w + gap), rect.bottom() - bh, w, bh), 1.2, 1.2)


class TrackDelegate(QStyledItemDelegate):
    def __init__(self, covers: Covers, state: State, numbered: bool = True):
        super().__init__()
        self.covers, self.state, self.numbered = covers, state, numbered

    def sizeHint(self, opt, index):
        return QSize(200, 60)

    def paint(self, p: QPainter, opt, index):
        t = index.data(TRACK_ROLE)
        if t is None:
            return
        p.save()
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        r = QRect(opt.rect).adjusted(6, 2, -6, -2)
        hover = bool(opt.state & QStyle.StateFlag.State_MouseOver)
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        playing = t.path == self.state.current_path
        accent = self.state.accent
        bg = None
        if selected:
            bg = QColor(255, 255, 255, 24)
        elif playing:
            bg = QColor(accent.red(), accent.green(), accent.blue(), 28)
        elif hover:
            bg = QColor(255, 255, 255, 12)
        if bg is not None:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(r, 8, 8)

        cols = track_columns(r.left(), r.width())
        cy = r.center().y()
        nx, nw = cols["num"]
        if playing:
            draw_eq(p, QRect(nx, cy - 8, nw, 16), accent, self.state.phase, self.state.playing)
        elif hover:
            f = QFont(ICON_FONT)
            f.setPixelSize(13)
            p.setFont(f)
            p.setPen(QColor(TEXT))
            p.drawText(QRect(nx, cy - 10, nw, 20), Qt.AlignmentFlag.AlignCenter, G.PLAY)
        elif self.numbered:
            p.setFont(ui_font(13))
            p.setPen(QColor(DIM))
            p.drawText(QRect(nx, cy - 10, nw, 20), Qt.AlignmentFlag.AlignCenter, str(index.row() + 1))

        cx, cw = cols["cover"]
        p.drawPixmap(cx, cy - cw // 2, self.covers.get(t.cover, cw, 6, seed=t.album_display))

        tx, tw = cols["title"]
        f = ui_font(14, QFont.Weight.DemiBold)
        p.setFont(f)
        p.setPen(accent.lighter(115) if playing else QColor(TEXT))
        fm = p.fontMetrics()
        p.drawText(QRect(tx, cy - 20, tw, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   fm.elidedText(t.title, Qt.TextElideMode.ElideRight, tw))
        p.setFont(ui_font(12))
        p.setPen(QColor(MUTED))
        fm = p.fontMetrics()
        p.drawText(QRect(tx, cy + 1, tw, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   fm.elidedText(t.artist_display, Qt.TextElideMode.ElideRight, tw))

        p.setFont(ui_font(13))
        fm = p.fontMetrics()
        if cols["album"]:
            ax, aw = cols["album"]
            p.drawText(QRect(ax, cy - 10, aw, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       fm.elidedText(t.album_display, Qt.TextElideMode.ElideRight, aw))
        if cols["year"]:
            yx, yw = cols["year"]
            p.drawText(QRect(yx, cy - 10, yw, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, t.year)
        lx, lw = cols["lyr"]
        draw_lyrics_mark(p, QRect(lx, cy - 10, lw, 20), self.state.lyrics_status(t.path), accent)
        p.setFont(ui_font(13))
        p.setPen(QColor(MUTED))
        dx, dw = cols["dur"]
        p.drawText(QRect(dx, cy - 10, dw, 20), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   fmt_time(t.duration))
        p.restore()

    def helpEvent(self, event, view, option, index):
        """Explica el indicador de letra al pasar el cursor sobre él."""
        t = index.data(TRACK_ROLE)
        if t is not None and event.type() == event.Type.ToolTip:
            r = QRect(option.rect).adjusted(6, 2, -6, -2)
            lx, lw = track_columns(r.left(), r.width())["lyr"]
            if lx <= event.pos().x() <= lx + lw:
                QToolTip.showText(event.globalPos(), LYRICS_TIPS.get(self.state.lyrics_status(t.path)), view)
                return True
        QToolTip.hideText()
        return super().helpEvent(event, view, option, index)


class CompactDelegate(QStyledItemDelegate):
    """Fila pequeña para «A continuación» en el panel derecho."""

    def __init__(self, covers: Covers):
        super().__init__()
        self.covers = covers

    def sizeHint(self, opt, index):
        return QSize(200, 52)

    def paint(self, p, opt, index):
        t = index.data(TRACK_ROLE)
        if t is None:
            return
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRect(opt.rect).adjusted(0, 2, 0, -2)
        if opt.state & QStyle.StateFlag.State_MouseOver:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 14))
            p.drawRoundedRect(r, 8, 8)
        p.drawPixmap(r.left() + 6, r.center().y() - 20, self.covers.get(t.cover, 40, 5, seed=t.album_display))
        tx, tw = r.left() + 58, r.width() - 64
        p.setFont(ui_font(13, QFont.Weight.DemiBold))
        p.setPen(QColor(TEXT))
        p.drawText(QRect(tx, r.center().y() - 19, tw, 19), Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(t.title, Qt.TextElideMode.ElideRight, tw))
        p.setFont(ui_font(12))
        p.setPen(QColor(MUTED))
        p.drawText(QRect(tx, r.center().y(), tw, 18), Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(t.artist_display, Qt.TextElideMode.ElideRight, tw))
        p.restore()


def grid_geometry(rect: QRect):
    r = rect.adjusted(6, 6, -6, -6)
    size = r.width() - 24
    size -= size % 4
    cover = QRect(r.left() + 12, r.top() + 12, size, size)
    play = QRect(cover.right() - 54, cover.bottom() - 54, 46, 46)
    return r, cover, play


class GridDelegate(QStyledItemDelegate):
    def __init__(self, covers: Covers, state: State, circle: bool):
        super().__init__()
        self.covers, self.state, self.circle = covers, state, circle
        self.grid = QSize(200, 270)

    def sizeHint(self, opt, index):
        return self.grid

    def paint(self, p, opt, index):
        it = index.data(ITEM_ROLE)
        if it is None:
            return
        p.save()
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        r, cover, play = grid_geometry(opt.rect)
        hover = bool(opt.state & QStyle.StateFlag.State_MouseOver)
        if hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 14))
            p.drawRoundedRect(r, 10, 10)
        p.drawPixmap(cover.topLeft(), self.covers.get(it.cover, cover.width(), 8, self.circle, seed=it.name))
        if hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 90))
            p.drawEllipse(play.adjusted(-1, 1, 1, 3))
            p.setBrush(self.state.accent)
            p.drawEllipse(play)
            f = QFont(ICON_FONT)
            f.setPixelSize(17)
            p.setFont(f)
            p.setPen(QColor("#0b0b0f") if self.state.accent.lightness() > 140 else QColor("white"))
            p.drawText(play.adjusted(2, 0, 2, 0), Qt.AlignmentFlag.AlignCenter, G.PLAY)
        align = Qt.AlignmentFlag.AlignHCenter if self.circle else Qt.AlignmentFlag.AlignLeft
        tw = cover.width()
        p.setFont(ui_font(14, QFont.Weight.DemiBold))
        p.setPen(QColor(TEXT))
        p.drawText(QRect(cover.left(), cover.bottom() + 10, tw, 20), align | Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(it.name, Qt.TextElideMode.ElideRight, tw))
        p.setFont(ui_font(12))
        p.setPen(QColor(MUTED))
        sub = it.subtitle if self.circle else " · ".join(x for x in (it.year, it.subtitle) if x)
        p.drawText(QRect(cover.left(), cover.bottom() + 30, tw, 18), align | Qt.AlignmentFlag.AlignVCenter,
                   p.fontMetrics().elidedText(sub, Qt.TextElideMode.ElideRight, tw))
        p.restore()


# ================================================================ vistas

class TrackView(QListView):
    def __init__(self, delegate):
        super().__init__()
        self.setItemDelegate(delegate)
        self.setMouseTracking(True)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(24)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)


class GridView(QListView):
    openItem = Signal(object)
    playItem = Signal(object)

    def __init__(self, delegate: GridDelegate):
        super().__init__()
        self.delegate = delegate
        self.setItemDelegate(delegate)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setWrapping(True)
        self.setSpacing(0)
        self.setMouseTracking(True)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(30)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def resizeEvent(self, e):
        w = self.viewport().width() - 4
        cols = max(2, w // 196)
        gw = w // cols
        size = QSize(gw, gw - 12 + 66)
        if size != self.delegate.grid:
            self.delegate.grid = size
            self.setGridSize(size)
        super().resizeEvent(e)

    def mouseReleaseEvent(self, e):
        idx = self.indexAt(e.position().toPoint())
        if idx.isValid() and e.button() == Qt.MouseButton.LeftButton:
            it = idx.data(ITEM_ROLE)
            _, _, play = grid_geometry(self.visualRect(idx))
            (self.playItem if play.contains(e.position().toPoint()) else self.openItem).emit(it)
        super().mouseReleaseEvent(e)


class ColumnHeader(QWidget):
    """Encabezados (#, Título, Álbum…) alineados con las filas de la lista."""

    sortRequested = Signal(str)

    def __init__(self, view: QListView, sort_state=None):
        super().__init__()
        self.view = view
        self.sort_state = sort_state  # función -> (modo, descendente); None = no ordenable
        self.setFixedHeight(34)
        if sort_state:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip("Clic en una columna para ordenar; otro clic invierte el orden")
        view.viewport().installEventFilter(self)

    def eventFilter(self, obj, e):
        if e.type() == e.Type.Resize:
            self.update()
        return False

    def _layout(self):
        r = QRect(0, 0, self.view.viewport().width(), self.height()).adjusted(6, 0, -6, 0)
        cols = track_columns(r.left(), r.width())
        tx = cols["cover"][0]
        title_end = (cols["album"] or cols["year"] or cols["dur"])[0]
        spans = [("track", "#", cols["num"], Qt.AlignmentFlag.AlignCenter),
                 ("title", "Título", (tx, title_end - tx), Qt.AlignmentFlag.AlignLeft),
                 ("album", "Álbum", cols["album"], Qt.AlignmentFlag.AlignLeft),
                 ("year", "Año", cols["year"], Qt.AlignmentFlag.AlignLeft),
                 ("lyrics", G.LYRICS, cols["lyr"], Qt.AlignmentFlag.AlignCenter),
                 ("duration", "Duración", cols["dur"], Qt.AlignmentFlag.AlignRight)]
        return r, [s for s in spans if s[2]]

    def mousePressEvent(self, e):
        if not self.sort_state or e.button() != Qt.MouseButton.LeftButton:
            return
        x = e.position().x()
        for mode, _, (cx, cw), _ in self._layout()[1]:
            if cx <= x <= cx + cw:
                self.sortRequested.emit(mode)
                return

    def paintEvent(self, _):
        p = QPainter(self)
        r, spans = self._layout()
        active, desc = self.sort_state() if self.sort_state else (None, False)
        label_font = ui_font(12, QFont.Weight.DemiBold)
        arrow_font = QFont(ICON_FONT)
        arrow_font.setPixelSize(10)
        mic_font = QFont(ICON_FONT)
        mic_font.setPixelSize(12)
        for mode, label, (x, w), align in spans:
            on = mode == active
            rect = QRect(x, 0, w, self.height())
            if mode == "lyrics":  # columna estrecha: el micrófono se colorea en vez de llevar flecha
                p.setFont(mic_font)
                p.setPen(self.accent() if on else QColor(MUTED))
                p.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
                continue
            p.setFont(label_font)
            p.setPen(QColor(TEXT) if on else QColor(MUTED))
            p.drawText(rect, align | Qt.AlignmentFlag.AlignVCenter, label)
            if on:
                tw = p.fontMetrics().horizontalAdvance(label)
                if align == Qt.AlignmentFlag.AlignRight:
                    ax = x + w - tw - 16
                elif align == Qt.AlignmentFlag.AlignCenter:
                    ax = x + (w + tw) // 2 + 2
                else:
                    ax = x + tw + 6
                p.setFont(arrow_font)
                p.setPen(self.accent())
                p.drawText(QRect(ax, 0, 12, self.height()), Qt.AlignmentFlag.AlignVCenter,
                           G.SORT_DOWN if desc else G.SORT_UP)
        p.setPen(QPen(QColor(255, 255, 255, 22), 1))
        p.drawLine(r.left(), self.height() - 1, r.right(), self.height() - 1)

    def accent(self) -> QColor:
        win = self.window()
        return win.state.accent.lighter(120) if hasattr(win, "state") else QColor(TEXT)


class Banner(QWidget):
    """Cabecera con degradado del color de la canción actual."""

    def __init__(self, state: State, covers: Covers):
        super().__init__()
        self.state, self.covers = state, covers
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 16, 28, 18)
        lay.setSpacing(14)

        top = QHBoxLayout()
        self.back = icon_button(G.BACK, "Volver")
        top.addWidget(self.back)
        top.addStretch(1)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Buscar canciones, artistas o álbumes")
        self.search.setFixedWidth(320)
        self.search.setClearButtonEnabled(True)
        self.search.addAction(glyph_icon(G.SEARCH, MUTED, MUTED, 16), QLineEdit.ActionPosition.LeadingPosition)
        self.sort = QComboBox()
        self.sort.setObjectName("sort")
        for label, _ in SORTS:
            self.sort.addItem(label)
        self.sort.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sort.setMaxVisibleItems(len(SORTS))
        self.order = icon_button(G.SORT_DOWN, "Invertir orden", "iconBtn", 34)
        top.addWidget(self.search)
        top.addSpacing(8)
        top.addWidget(self.sort)
        top.addWidget(self.order)
        lay.addLayout(top)

        mid = QHBoxLayout()
        mid.setSpacing(22)
        self.cover = QLabel()
        self.cover.setFixedSize(150, 150)
        mid.addWidget(self.cover, 0, Qt.AlignmentFlag.AlignBottom)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addStretch(1)
        self.kicker = QLabel()
        self.kicker.setObjectName("kicker")
        self.title = ElidedLabel("", "bannerTitle")
        self.sub = ElidedLabel("", "bannerSub")
        col.addWidget(self.kicker)
        col.addWidget(self.title)
        col.addWidget(self.sub)
        mid.addLayout(col, 1)
        lay.addLayout(mid)

        actions = QHBoxLayout()
        actions.setSpacing(12)
        self.play = icon_button(G.PLAY, "Reproducir", "bigPlay", 56)
        self.shuffle = QPushButton(" Aleatorio")
        self.shuffle.setObjectName("pill")
        self.shuffle.setIcon(glyph_icon(G.SHUFFLE, TEXT, TEXT, 16))
        self.shuffle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.shuffle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        actions.addWidget(self.play)
        actions.addWidget(self.shuffle)
        actions.addStretch(1)
        lay.addLayout(actions)

    def set_sort_visible(self, visible: bool):
        self.sort.setVisible(visible)
        self.order.setVisible(visible)

    def set_cover(self, path: str | None, circle: bool = False, seed: str = ""):
        if path is None:
            self.cover.hide()
            return
        self.cover.setPixmap(self.covers.get(path, 150, 10, circle, seed))
        self.cover.show()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0, self.state.accent.darker(185))
        g.setColorAt(1, QColor(PANEL))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        r = QRectF(self.rect())
        p.drawRoundedRect(r, 12, 12)
        p.drawRect(r.adjusted(0, 12, 0, 0))


class NowPanel(QWidget):
    """Panel derecho «Reproduciendo ahora»."""

    def __init__(self, state: State, covers: Covers):
        super().__init__()
        self.state, self.covers = state, covers
        self.setFixedWidth(320)
        self.track = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 12)
        lay.setSpacing(6)
        k = QLabel("Reproduciendo ahora")
        k.setObjectName("panelKicker")
        lay.addWidget(k)
        lay.addSpacing(8)
        self.cover = QLabel()
        self.cover.setFixedSize(288, 288)
        lay.addWidget(self.cover)
        lay.addSpacing(8)
        self.title = ElidedLabel("", "panelTitle")
        self.artist = ElidedLabel("", "panelArtist")
        self.album = ElidedLabel("", "panelAlbum")
        for w in (self.title, self.artist, self.album):
            lay.addWidget(w)
        lay.addSpacing(12)
        self.lyrics_card = LyricsCard(state)
        lay.addWidget(self.lyrics_card)
        lay.addSpacing(14)
        h = QLabel("A continuación")
        h.setObjectName("panelHeading")
        lay.addWidget(h)
        self.next_model = TrackModel()
        self.next_view = TrackView(CompactDelegate(covers))
        self.next_view.setModel(self.next_model)
        self.next_view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        lay.addWidget(self.next_view, 1)
        self.set_track(None)

    def set_track(self, t):
        self.track = t
        if t is None:
            self.cover.setPixmap(self.covers.get("", 288, 12, seed="sonora"))
            self.title.setText("Nada en reproducción")
            self.artist.setText("Elige una canción para empezar")
            self.album.setText("")
        else:
            self.cover.setPixmap(self.covers.get(t.cover, 288, 12, seed=t.album_display))
            self.title.setText(t.title)
            self.artist.setText(t.artist_display)
            self.album.setText(" · ".join(x for x in (t.album_display, t.year) if x))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(r, 12, 12)
        p.fillPath(path, QColor(PANEL))
        g = QLinearGradient(0, 0, 0, r.height() * 0.6)
        top = self.state.accent.darker(200)
        top.setAlpha(230)
        g.setColorAt(0, top)
        g.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillPath(path, g)


class SourcesDialog(QDialog):
    """Fuentes de letras: LRCLIB siempre; NetEase opcional (desactivada por defecto)."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Fuentes de letras")
        self.resize(560, 330)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(10)
        t = QLabel("Fuentes de letras")
        t.setObjectName("emptyTitle")
        lay.addWidget(t)
        intro = QLabel("Sonora primero usa tus archivos .lrc y la letra guardada en la canción; "
                       "si no hay, la busca en internet en estas fuentes:")
        intro.setObjectName("emptySub")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        lay.addSpacing(6)
        lrclib = QCheckBox("LRCLIB  ·  fuente principal (gratuita y abierta)")
        lrclib.setChecked(True)
        lrclib.setEnabled(False)
        lay.addWidget(lrclib)
        self.netease = QCheckBox("NetEase Cloud Music  ·  respaldo opcional")
        self.netease.setChecked(lyrics_mod.SOURCES["netease"])
        self.netease.setCursor(Qt.CursorShape.PointingHandCursor)
        lay.addWidget(self.netease)
        note = QLabel("Se usa sólo cuando LRCLIB no tiene la letra o no responde. Es un servicio chino con "
                      "muchas letras sincronizadas de canciones conocidas, pero Sonora lo consulta mediante "
                      "una API no oficial: puede dejar de funcionar o bloquear consultas sin aviso. "
                      "Al activarlo, las canciones marcadas «sin letra» se vuelven a revisar.")
        note.setObjectName("emptySub")
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        done = QPushButton("Listo")
        done.setObjectName("accentPill")
        done.setCursor(Qt.CursorShape.PointingHandCursor)
        row.addWidget(done)
        lay.addLayout(row)
        done.clicked.connect(self.accept)
        self.netease.toggled.connect(win.set_netease)

    def showEvent(self, e):
        super().showEvent(e)
        dark_title_bar(self)


class FoldersDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Carpetas de música")
        self.resize(560, 360)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(12)
        t = QLabel("Carpetas de música")
        t.setObjectName("emptyTitle")
        s = QLabel("Sonora vigila estas carpetas y agrega automáticamente la música que encuentre.")
        s.setObjectName("emptySub")
        s.setWordWrap(True)
        lay.addWidget(t)
        lay.addWidget(s)
        self.list = QListWidget()
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        add = QPushButton("Agregar carpeta")
        add.setObjectName("accentPill")
        rem = QPushButton("Quitar seleccionada")
        rem.setObjectName("pill")
        close = QPushButton("Listo")
        close.setObjectName("pill")
        for b in (add, rem):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)
        add.clicked.connect(self._add)
        rem.clicked.connect(self._remove)
        close.clicked.connect(self.accept)
        self._fill()

    def showEvent(self, e):
        super().showEvent(e)
        dark_title_bar(self)

    def _fill(self):
        self.list.clear()
        self.list.addItems(self.win.library.folders)

    def _add(self):
        self.win.choose_folder()
        self._fill()

    def _remove(self):
        item = self.list.currentItem()
        if item:
            self.win.remove_folder(item.text())
            self._fill()


# ================================================================ ventana principal

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = open_settings()
        lyrics_mod.SOURCES["netease"] = self.settings.value("netease", False, type=bool)  # opcional
        self.library = Library()
        self.state = State()
        self.covers = Covers()
        self.player = Player(self)
        self.lyrics_service = LyricsService()
        self.state.lyrics_status = self.lyrics_service.status_of
        self.lyrics_tick = QTimer(self, singleShot=True, interval=800, timeout=self._refresh_lyrics_status)
        self.lyrics_trouble = 0      # segundos hasta el reintento si LRCLIB no responde
        self._lyrics_done = None     # para avisar una sola vez cuando termina la revisión
        self._last_none = -1
        self.current_lyrics = None
        self.lyric_index = None
        self.lyric_status = ""
        self.lyrics_prefetch = QTimer(self, singleShot=True, interval=4000, timeout=self._prefetch_lyrics)
        self.publisher = Publisher()
        self.editor_return = None
        self.scanner = None
        self.rescan_pending = False
        self.mini = None
        self.media_keys = None
        self.taskbar = None
        self.page = "songs"
        self.detail = None          # ("album" | "artist", key)
        self.accent_cache: dict[str, QColor] = {}
        self.sorts = dict(DEFAULT_SORTS)
        self.albums, self.artists, self.folders = [], [], []
        self.dragging_seek = False

        self.setWindowTitle("Sonora")
        self.resize(1320, 820)
        self.setMinimumSize(980, 620)
        self.setAcceptDrops(True)

        self.refresh_timer = QTimer(self, singleShot=True, interval=500, timeout=self.refresh_library)
        self.eq_timer = QTimer(self, interval=110, timeout=self._tick_eq)
        self.search_timer = QTimer(self, singleShot=True, interval=140, timeout=self._on_search)
        self.watch_timer = QTimer(self, singleShot=True, interval=2500, timeout=self.start_scan)
        self.status_timer = QTimer(self, singleShot=True, interval=6000,
                                   timeout=lambda: self.scan_label.setText(""))
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(lambda _: self.watch_timer.start())
        self.scan_new = self.scan_removed = 0
        self.scan_manual = False

        self._build()
        self._connect()
        QApplication.instance().setStyleSheet(build_qss(DEFAULT_ACCENT))  # una sola vez
        self._accent_applied = False
        self.apply_accent(DEFAULT_ACCENT)
        self._restore_settings()
        self.refresh_library()
        self._restore_last_track()
        self.songs_view.setFocus()
        self.lyrics_service.start()
        QTimer.singleShot(400, self._initial_scan)

    # ------------------------------------------------------------ construcción
    def _build(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(8, 8, 8, 0)
        outer.setSpacing(0)
        body = QHBoxLayout()
        body.setSpacing(8)
        outer.addLayout(body, 1)
        body.addWidget(self._build_sidebar())
        body.addWidget(self._build_content(), 1)
        self.now_panel = NowPanel(self.state, self.covers)
        self.now_panel.next_view.doubleClicked.connect(
            lambda idx: self.player.jump(self.player.pos + 1 + idx.row()))
        self.now_panel.lyrics_card.clicked.connect(self.show_lyrics)
        body.addWidget(self.now_panel)
        self.player_bar = self._build_player_bar()
        outer.addWidget(self.player_bar)

    def _build_sidebar(self):
        side = QFrame()
        side.setObjectName("panel")
        side.setFixedWidth(232)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(12, 18, 12, 14)
        lay.setSpacing(4)

        logo_row = QHBoxLayout()
        logo_row.setContentsMargins(10, 0, 0, 0)
        icon = QLabel()
        icon.setPixmap(self.windowIcon().pixmap(30, 30) if not self.windowIcon().isNull()
                       else QApplication.windowIcon().pixmap(30, 30))
        logo = QLabel("Sonora")
        logo.setObjectName("logo")
        logo_row.addWidget(icon)
        logo_row.addSpacing(6)
        logo_row.addWidget(logo)
        badge = QLabel(APP_VERSION)
        badge.setObjectName("versionBadge")
        logo_row.addSpacing(6)
        logo_row.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)
        logo_row.addStretch(1)
        lay.addLayout(logo_row)
        lay.addSpacing(22)

        self.nav = QButtonGroup(self)
        self.nav_buttons = {}
        for key, glyph, label in (("songs", G.MUSIC, "Canciones"), ("albums", G.ALBUM, "Álbumes"),
                                  ("artists", G.ARTIST, "Artistas"), ("folders", G.FOLDER, "Carpetas"),
                                  ("nolyrics", G.LYRICS, "Sin letra"),
                                  ("queue", G.QUEUE, "Cola de reproducción")):
            b = QPushButton("  " + label)
            b.setObjectName("navButton")
            b.setCheckable(True)
            b.setIcon(glyph_icon(glyph))
            b.setIconSize(QSize(18, 18))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda _=False, k=key: self.show_page(k))
            self.nav.addButton(b)
            self.nav_buttons[key] = b
            lay.addWidget(b)

        lay.addSpacing(18)
        sec = QLabel("BIBLIOTECA")
        sec.setObjectName("sectionLabel")
        lay.addWidget(sec)
        lay.addSpacing(4)
        for glyph, label, slot in ((G.REFRESH, "Actualizar biblioteca", self.rescan),
                                   (G.FOLDER, "Agregar carpeta", self.choose_folder),
                                   (G.FILE, "Abrir archivos", self.choose_files),
                                   (G.SETTINGS, "Administrar carpetas", self.manage_folders),
                                   (G.GLOBE, "Fuentes de letras", self.manage_sources)):
            b = QPushButton("  " + label)
            b.setObjectName("navButton")
            b.setIcon(glyph_icon(glyph))
            b.setIconSize(QSize(18, 18))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(slot)
            lay.addWidget(b)
            if slot == self.rescan:
                b.setToolTip("Busca canciones nuevas y quita las eliminadas (F5)")
                self.refresh_btn = b

        lay.addStretch(1)
        self.scan_label = QLabel("")
        self.scan_label.setObjectName("scanLabel")
        self.scan_label.setWordWrap(True)
        lay.addWidget(self.scan_label)
        self.lyrics_label = QLabel("")
        self.lyrics_label.setObjectName("scanLabel")
        self.lyrics_label.setWordWrap(True)
        lay.addWidget(self.lyrics_label)
        lay.addSpacing(8)
        mini = QPushButton("  Minireproductor")
        mini.setObjectName("pill")
        mini.setIcon(glyph_icon(G.MINI, TEXT, TEXT, 16))
        mini.setCursor(Qt.CursorShape.PointingHandCursor)
        mini.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        mini.clicked.connect(self.show_mini)
        lay.addWidget(mini)
        return side

    def _build_content(self):
        content = QFrame()
        content.setObjectName("panel")
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.banner = Banner(self.state, self.covers)
        lay.addWidget(self.banner)

        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)

        # canciones
        self.track_proxy = SongsModel()
        self.track_proxy.lyrics_status = self.lyrics_service.status_of
        self.songs_view = TrackView(TrackDelegate(self.covers, self.state))
        self.songs_view.setModel(self.track_proxy)
        songs = QWidget()
        sl = QVBoxLayout(songs)
        sl.setContentsMargins(16, 4, 10, 0)
        sl.setSpacing(4)
        self.songs_header = ColumnHeader(self.songs_view, lambda: self.sorts[self._sort_context()])
        self.songs_header.sortRequested.connect(self._header_sort)
        sl.addWidget(self.songs_header)
        sl.addWidget(self.songs_view, 1)
        self.stack.addWidget(songs)

        # álbumes, artistas y carpetas
        self.album_model, self.artist_model, self.folder_model = GridModel(), GridModel(), GridModel()
        self.grid_proxies = []
        self.grids = {}
        for key, kind, model, circle in (("albums", "album", self.album_model, False),
                                         ("artists", "artist", self.artist_model, True),
                                         ("folders", "folder", self.folder_model, False)):
            proxy = QSortFilterProxyModel()
            proxy.setSourceModel(model)
            proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            self.grid_proxies.append(proxy)
            view = GridView(GridDelegate(self.covers, self.state, circle))
            view.setModel(proxy)
            view.openItem.connect(lambda it, k=kind: self.open_detail(k, it))
            view.playItem.connect(lambda it: self.player.play_list(it.tracks, 0))
            wrap = QWidget()
            wl = QVBoxLayout(wrap)
            wl.setContentsMargins(16, 4, 10, 0)
            wl.addWidget(view)
            self.stack.addWidget(wrap)
            self.grids[key] = (view, wrap)

        # cola
        self.queue_model = TrackModel()
        self.queue_view = TrackView(TrackDelegate(self.covers, self.state))
        self.queue_view.setModel(self.queue_model)
        queue = QWidget()
        ql = QVBoxLayout(queue)
        ql.setContentsMargins(16, 4, 10, 0)
        ql.addWidget(ColumnHeader(self.queue_view))
        ql.addWidget(self.queue_view, 1)
        self.stack.addWidget(queue)
        self.queue_page = queue
        self.songs_page = songs

        # biblioteca vacía
        empty = QWidget()
        el = QVBoxLayout(empty)
        el.addStretch(1)
        et = QLabel("Tu biblioteca está vacía")
        et.setObjectName("emptyTitle")
        es = QLabel("Agrega una carpeta con música o arrastra archivos aquí.\n"
                    "Formatos: MP3, FLAC, WAV, OGG, OPUS, M4A/AAC, WMA, AIFF, ALAC, APE y más.")
        es.setObjectName("emptySub")
        es.setAlignment(Qt.AlignmentFlag.AlignCenter)
        eb = QPushButton("Agregar carpeta")
        eb.setObjectName("accentPill")
        eb.setCursor(Qt.CursorShape.PointingHandCursor)
        eb.clicked.connect(self.choose_folder)
        for w in (et, es):
            el.addWidget(w, 0, Qt.AlignmentFlag.AlignHCenter)
        el.addSpacing(12)
        el.addWidget(eb, 0, Qt.AlignmentFlag.AlignHCenter)
        el.addStretch(2)
        self.stack.addWidget(empty)

        # letra
        self.lyrics_page = LyricsPage(self.state, self.covers)
        self.lyrics_page.closeRequested.connect(self.close_lyrics)
        self.lyrics_page.retryRequested.connect(self._retry_lyrics)
        self.lyrics_page.view.seekRequested.connect(self.player.seek)
        self.lyrics_page.editRequested.connect(lambda: self.open_editor())
        self.stack.addWidget(self.lyrics_page)

        # editor de letras
        self.editor = LyricsEditor(self.state, self.covers, self.player)
        self.editor.closeRequested.connect(self.close_editor)
        self.editor.saveRequested.connect(self._save_user_lyrics)
        self.stack.addWidget(self.editor)
        self.empty_page = empty
        return content

    def _build_player_bar(self):
        bar = QFrame()
        bar.setObjectName("playerBar")
        bar.setFixedHeight(92)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(10, 8, 14, 8)

        left = QWidget()
        left.setFixedWidth(320)
        ll = QHBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(12)
        self.bar_cover = QLabel()
        self.bar_cover.setFixedSize(58, 58)
        ll.addWidget(self.bar_cover)
        tl = QVBoxLayout()
        tl.setSpacing(0)
        tl.addStretch(1)
        self.bar_title = ElidedLabel("", "nowTitle")
        self.bar_artist = ElidedLabel("", "nowArtist")
        tl.addWidget(self.bar_title)
        tl.addWidget(self.bar_artist)
        tl.addStretch(1)
        ll.addLayout(tl, 1)
        lay.addWidget(left)

        center = QVBoxLayout()
        center.setSpacing(4)
        btns = QHBoxLayout()
        btns.setSpacing(10)
        btns.addStretch(1)
        self.shuffle_btn = icon_button(G.SHUFFLE, "Aleatorio")
        self.prev_btn = icon_button(G.PREV, "Anterior (Ctrl+←)")
        self.play_btn = icon_button(G.PLAY, "Reproducir (Espacio)", "playBtn", 40)
        self.next_btn = icon_button(G.NEXT, "Siguiente (Ctrl+→)")
        self.repeat_btn = icon_button(G.REPEAT_ALL, "Repetir")
        for b in (self.shuffle_btn, self.prev_btn, self.play_btn, self.next_btn, self.repeat_btn):
            btns.addWidget(b)
        btns.addStretch(1)
        center.addLayout(btns)
        seek_row = QHBoxLayout()
        seek_row.setSpacing(10)
        self.pos_lbl = QLabel("0:00")
        self.pos_lbl.setObjectName("time")
        self.pos_lbl.setFixedWidth(46)
        self.pos_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.dur_lbl = QLabel("0:00")
        self.dur_lbl.setObjectName("time")
        self.dur_lbl.setFixedWidth(46)
        self.seek = ClickSlider(wheel=False)
        seek_row.addWidget(self.pos_lbl)
        seek_row.addWidget(self.seek, 1)
        seek_row.addWidget(self.dur_lbl)
        center.addLayout(seek_row)
        lay.addLayout(center, 1)

        right = QWidget()
        right.setFixedWidth(320)
        rl = QHBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4)
        rl.addStretch(1)
        self.lyrics_btn = icon_button(G.LYRICS, "Letra (Ctrl+L)")
        self.queue_btn = icon_button(G.QUEUE, "Cola de reproducción")
        self.panel_btn = icon_button(G.PANEL, "Mostrar/ocultar panel")
        self.vol_btn = icon_button(G.VOLUME, "Silenciar")
        self.volume = ClickSlider()
        self.volume.setRange(0, 100)
        self.volume.setFixedWidth(110)
        self.mini_btn = icon_button(G.MINI, "Minireproductor (Ctrl+M)")
        for w in (self.lyrics_btn, self.queue_btn, self.panel_btn, self.vol_btn, self.volume, self.mini_btn):
            rl.addWidget(w)
        lay.addWidget(right)
        return bar

    def _connect(self):
        b = self.banner
        b.back.clicked.connect(self.close_detail)
        b.search.textChanged.connect(lambda _: self.search_timer.start())
        b.sort.activated.connect(lambda i: self.set_sort(SORTS[i][1]))
        b.order.clicked.connect(self.toggle_order)
        b.play.clicked.connect(lambda: self.play_view(shuffle=False))
        b.shuffle.clicked.connect(lambda: self.play_view(shuffle=True))

        self.songs_view.doubleClicked.connect(self._play_from_songs)
        self.songs_view.customContextMenuRequested.connect(lambda pos: self._track_menu(self.songs_view, pos))
        self.queue_view.doubleClicked.connect(lambda idx: self.player.jump(idx.row()))
        self.queue_view.customContextMenuRequested.connect(lambda pos: self._track_menu(self.queue_view, pos))

        self.play_btn.clicked.connect(self.toggle_play)
        self.prev_btn.clicked.connect(self.player.prev)
        self.next_btn.clicked.connect(lambda: self.player.next())
        self.shuffle_btn.clicked.connect(lambda: self.player.set_shuffle(not self.player.shuffle))
        self.repeat_btn.clicked.connect(self.player.cycle_repeat)
        self.queue_btn.clicked.connect(lambda: self.show_page("queue"))
        self.lyrics_btn.clicked.connect(self.toggle_lyrics)
        self.lyrics_service.ready.connect(self._on_lyrics)
        self.lyrics_service.failed.connect(self._on_lyrics_failed)
        self.lyrics_service.statusChanged.connect(lambda *_: self.lyrics_tick.isActive() or self.lyrics_tick.start())
        self.lyrics_service.serverTrouble.connect(self._on_lyrics_trouble)
        self.publisher.progress.connect(lambda msg: self.editor.set_status(msg))
        self.publisher.done.connect(self._on_published)
        self.editor.cancel_pub.clicked.connect(self.publisher.cancel)
        self.panel_btn.clicked.connect(lambda: self.now_panel.setVisible(not self.now_panel.isVisible()))
        self.vol_btn.clicked.connect(self.toggle_mute)
        self.volume.valueChanged.connect(self._on_volume)
        self.mini_btn.clicked.connect(self.show_mini)

        self.seek.sliderPressed.connect(lambda: setattr(self, "dragging_seek", True))
        self.seek.sliderReleased.connect(self._on_seek_release)
        self.seek.sliderMoved.connect(lambda v: self.pos_lbl.setText(fmt_time(v / 1000)))

        p = self.player
        p.trackChanged.connect(self._on_track)
        p.playingChanged.connect(self._on_playing)
        p.positionChanged.connect(self._on_position)
        p.durationChanged.connect(self._on_duration)
        p.queueChanged.connect(self._on_queue)
        p.modesChanged.connect(self._sync_modes)

        QShortcut(QKeySequence(Qt.Key.Key_Space), self, activated=self._on_space)
        QShortcut(QKeySequence("Ctrl+Right"), self, activated=lambda: self.player.next())
        QShortcut(QKeySequence("Ctrl+Left"), self, activated=self.player.prev)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=lambda: self.banner.search.setFocus())
        QShortcut(QKeySequence("Ctrl+M"), self, activated=self.show_mini)
        QShortcut(QKeySequence("F5"), self, activated=self.rescan)
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self.toggle_lyrics)
        QShortcut(QKeySequence("Ctrl+Up"), self, activated=lambda: self.change_volume(5))
        QShortcut(QKeySequence("Ctrl+Down"), self, activated=lambda: self.change_volume(-5))

    # ------------------------------------------------------------ biblioteca
    def refresh_library(self):
        tracks = self.library.all()
        self.lyrics_service.set_tracks(sorted(tracks, key=lambda t: -t.added))
        self.lyrics_tick.start()
        self.track_proxy.source = tracks  # show_page/open_detail reconstruyen la lista
        self.albums = group_albums(tracks)
        self.artists = group_artists(tracks)
        self.folders = group_folders(tracks)
        self.album_model.set_items(self.albums)
        self.artist_model.set_items(self.artists)
        self.folder_model.set_items(self.folders)
        if self.stack.currentWidget() in (self.lyrics_page, self.editor):
            self.track_proxy.configure()  # actualizar la lista sin sacar al usuario de la letra/editor
            return
        if self.detail:
            kind, key = self.detail
            group = self._find_group(kind, key)
            if group:
                self.open_detail(kind, group)
            else:
                self.close_detail()
        else:
            self.show_page(self.page)

    def _find_group(self, kind, key):
        items = {"album": self.albums, "artist": self.artists, "folder": self.folders}[kind]
        return next((g for g in items if g.key == key), None)

    def _initial_scan(self):
        if self.library.first_run and not self.library.folders:
            music = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.MusicLocation)
            if music and os.path.isdir(music):
                self.library.folders.append(os.path.normpath(music))
        self.start_scan()

    def rescan(self):
        """Botón «Actualizar biblioteca» / F5: busca archivos nuevos, cambiados y eliminados."""
        if not self.library.folders:
            self.scan_label.setText("Agrega una carpeta primero")
            self.status_timer.start()
            return
        self.scan_manual = True
        self.start_scan()

    def start_scan(self):
        if not self.library.folders:
            return
        if self.scanner is not None:
            self.rescan_pending = True
            return
        known = {t.path: t.mtime for t in self.library.all()}
        self.status_timer.stop()
        self.scanner = Scanner(self.library.folders, known)
        self.scanner.batch.connect(self._on_scan_batch)
        self.scanner.progress.connect(lambda n: self.scan_label.setText(
            f"Analizando música… {n} archivos" if n else "Buscando cambios…"))
        self.scanner.finished_scan.connect(self._on_scan_done)
        self.scan_label.setText("Buscando cambios…")
        self.refresh_btn.setEnabled(False)
        self.scanner.start()

    def _on_scan_batch(self, tracks):
        self.scan_new += sum(1 for t in tracks if t.path not in self.library.tracks)
        self.library.add(tracks)
        self.refresh_timer.start()

    def _on_scan_done(self, removed):
        self.library.remove(removed)
        self.library.save()
        self.scanner.wait()
        self.scanner = None
        self.scan_removed += len(removed)
        if removed or self.scan_new:
            self.refresh_timer.start()
        if self.rescan_pending:  # llegaron más cambios durante el escaneo: seguir acumulando
            self.rescan_pending = False
            self.start_scan()
            return
        self.refresh_btn.setEnabled(True)
        parts = []
        if self.scan_new:
            parts.append(f"{self.scan_new} nueva" + ("s" if self.scan_new != 1 else ""))
        if self.scan_removed:
            parts.append(f"{self.scan_removed} eliminada" + ("s" if self.scan_removed != 1 else ""))
        if parts:
            self.scan_label.setText("✓ " + " · ".join(parts))
        elif self.scan_manual:
            self.scan_label.setText("✓ La biblioteca está al día")
        else:
            self.scan_label.setText("")
        self.scan_new = self.scan_removed = 0
        self.scan_manual = False
        self.status_timer.start()
        self._watch_folders()

    def _watch_folders(self):
        """Vigila las carpetas para detectar canciones agregadas o borradas automáticamente."""
        dirs = set()
        for root in self.library.folders:
            if os.path.isdir(root):
                dirs.add(root)
        for t in self.library.tracks.values():
            dirs.add(os.path.dirname(t.path))
            if len(dirs) >= 1000:
                break
        dirs = {d for d in dirs if os.path.isdir(d)}
        current = set(self.watcher.directories())
        if current - dirs:
            self.watcher.removePaths(list(current - dirs))
        if dirs - current:
            self.watcher.addPaths(list(dirs - current))

    def choose_folder(self):
        start = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.MusicLocation)
        folder = QFileDialog.getExistingDirectory(self, "Elegir carpeta de música", start)
        if folder:
            self.add_folder(folder)

    def add_folder(self, folder):
        folder = os.path.normpath(folder)
        if folder not in self.library.folders:
            self.library.folders.append(folder)
            self.library.save()
        self.start_scan()

    def remove_folder(self, folder):
        self.library.remove_folder(folder)
        self.library.save()
        self.refresh_library()
        self._watch_folders()

    def manage_folders(self):
        FoldersDialog(self).exec()

    def manage_sources(self):
        SourcesDialog(self).exec()

    def set_netease(self, enabled: bool):
        self.settings.setValue("netease", enabled)
        lyrics_mod.SOURCES["netease"] = enabled
        if enabled:
            self.lyrics_service.sources_changed()

    def choose_files(self):
        exts = " ".join(f"*{e}" for e in sorted(AUDIO_EXTS))
        files, _ = QFileDialog.getOpenFileNames(self, "Abrir archivos de audio", "",
                                                f"Audio ({exts});;Todos los archivos (*.*)")
        if files:
            self.open_paths(files)

    def open_paths(self, paths):
        """Abre archivos/carpetas (línea de comandos o arrastrar y soltar)."""
        files = []
        for p in paths:
            p = os.path.normpath(p)
            if os.path.isdir(p):
                self.add_folder(p)
            elif os.path.isfile(p) and is_audio(p):
                files.append(p)
        if not files:
            return
        tracks = [self.library.tracks.get(f) or read_track(f) for f in files]
        self.library.add([t for t in tracks if t.path not in self.library.tracks])
        self.library.save()
        self.refresh_library()
        self.player.play_list(tracks, 0)

    # ------------------------------------------------------------ navegación
    def _leave_lyrics(self):
        self.banner.show()
        set_active(self.lyrics_btn, False)

    def toggle_lyrics(self):
        if self.stack.currentWidget() is self.lyrics_page:
            self.close_lyrics()
        else:
            self.show_lyrics()

    def show_lyrics(self):
        self.banner.hide()
        set_active(self.lyrics_btn, True)
        self.nav.setExclusive(False)
        for b in self.nav_buttons.values():
            b.setChecked(False)
        self.nav.setExclusive(True)
        self.stack.setCurrentWidget(self.lyrics_page)
        self.lyrics_page.view.set_position(self.player.mp.position(), snap=True)

    def close_lyrics(self):
        """Vuelve a la vista desde la que se abrió la letra."""
        if self.detail:
            group = self._find_group(*self.detail)
            if group:
                self.open_detail(self.detail[0], group)
                self.nav_buttons[self.page].setChecked(True)
                return
        self.show_page(self.page)

    # ------------------------------------------------------------ editor de letras
    def _on_space(self):
        """Espacio: marca la línea en el editor (paso Sincronizar) o reproduce/pausa."""
        if self.stack.currentWidget() is self.editor and self.editor.on_sync_page():
            self.editor.mark()
        else:
            self.toggle_play()

    def open_editor(self, track=None):
        t = track or self.player.current
        if t is None:
            return
        if self.publisher.busy and self.editor.track is not None and self.editor.track.path != t.path:
            QMessageBox.information(self, "Publicación en curso",
                                    "Espera a que termine de publicarse la letra anterior.")
            return
        if t.path != self.state.current_path:
            # Para sincronizar, la canción tiene que ser la que suena: se pone a continuación y en pausa.
            if self.player.current is None:
                self.player.play_list([t], 0, play=False)
            else:
                self.player.play_next([t])
                self.player.next()
                self.player.mp.pause()
        known, lyr = self.lyrics_service.cached(t.path)
        if not known:
            lyr = load_local(t)
        self.editor_return = "lyrics" if self.stack.currentWidget() is self.lyrics_page else None
        self.banner.hide()
        self.nav.setExclusive(False)
        for b in self.nav_buttons.values():
            b.setChecked(False)
        self.nav.setExclusive(True)
        self.editor.open(t, lyr)
        self.stack.setCurrentWidget(self.editor)

    def close_editor(self):
        if self.editor_return == "lyrics":
            self.show_lyrics()
        else:
            self.close_lyrics()

    def _save_user_lyrics(self, t, lyr, meta, publish):
        try:
            where = self.lyrics_service.store_user_lyrics(t, lyr)
        except OSError as e:
            self.editor.set_status(f"No se pudo guardar la letra: {e}", False)
            return
        if not publish:
            self.editor.set_status(f"✓ Guardada en {where}", True)
            return
        _, plain, synced = self.editor.build_lyrics()
        kind = ("instrumental (sin letra)" if lyr.instrumental else
                "sincronizada" if synced else "sin sincronizar")
        box = QMessageBox(self)
        box.setWindowTitle("Publicar en LRCLIB")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText("¿Publicar esta letra en LRCLIB?")
        box.setInformativeText(
            "Se enviará de forma pública:\n\n"
            f"   Título:   {meta['trackName']}\n   Artista:   {meta['artistName']}\n"
            f"   Álbum:   {meta['albumName']}\n   Duración:   {meta['duration']} s\n   Letra:   {kind}\n\n"
            "Cualquier persona podrá verla y no se puede borrar desde Sonora.")
        publish_btn = box.addButton("Publicar", QMessageBox.ButtonRole.AcceptRole)
        cancel_btn = box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel_btn)
        box.exec()
        if box.clickedButton() is not publish_btn:
            self.editor.set_status(f"✓ Guardada en {where} (no se publicó)", True)
            return
        self.editor.set_status(f"✓ Guardada en {where}. Preparando la publicación…")
        self.editor.set_publishing(True)
        self.publisher.start(meta, plain, synced)

    def _on_published(self, ok, message):
        self.editor.set_publishing(False)
        self.editor.set_status(message, ok)
        if not self.editor.isVisible():
            self.lyrics_label.setText(message)

    def show_page(self, name):
        self._leave_lyrics()
        self.page = name
        self.detail = None
        self.nav_buttons[name].setChecked(True)
        b = self.banner
        b.back.hide()
        b.set_cover(None)
        b.set_sort_visible(name in ("songs", "nolyrics"))
        b.search.setVisible(name != "queue")
        b.play.show()
        b.shuffle.show()
        self._apply_sort(scope=("nolyrics", None) if name == "nolyrics" else None)
        if not self.library.tracks and name != "queue":
            b.kicker.setText("BIBLIOTECA")
            b.title.setText("Sonora")
            b.sub.setText("")
            b.play.hide()
            b.shuffle.hide()
            self.stack.setCurrentWidget(self.empty_page)
            return
        if name == "songs":
            tracks = self.library.all()
            b.kicker.setText("BIBLIOTECA")
            b.title.setText("Canciones")
            b.sub.setText(f"{len(tracks)} canciones · {fmt_total(sum(t.duration for t in tracks))}")
            self.stack.setCurrentWidget(self.songs_page)
        elif name == "nolyrics":
            b.kicker.setText("LETRAS")
            b.title.setText("Sin letra")
            b.sub.setText(self._nolyrics_subtitle())
            self.stack.setCurrentWidget(self.songs_page)
        elif name in self.grids:
            title, items, noun = {"albums": ("Álbumes", self.albums, "álbumes"),
                                  "artists": ("Artistas", self.artists, "artistas"),
                                  "folders": ("Carpetas", self.folders, "carpetas")}[name]
            b.kicker.setText("BIBLIOTECA")
            b.title.setText(title)
            b.sub.setText(f"{len(items)} {noun}")
            self.stack.setCurrentWidget(self.grids[name][1])
        elif name == "queue":
            q = self.player.ordered()
            b.kicker.setText("REPRODUCIENDO")
            b.title.setText("Cola de reproducción")
            b.sub.setText(f"{len(q)} canciones · {fmt_total(sum(t.duration for t in q))}" if q
                          else "La cola está vacía")
            self.stack.setCurrentWidget(self.queue_page)
            self._scroll_queue()

    def open_detail(self, kind, group):
        self._leave_lyrics()
        self.detail = (kind, group.key)
        b = self.banner
        b.back.show()
        b.set_sort_visible(True)
        b.play.show()
        b.shuffle.show()
        total = fmt_total(sum(t.duration for t in group.tracks))
        n = len(group.tracks)
        count = f"{n} canción" if n == 1 else f"{n} canciones"
        if kind == "album":
            b.kicker.setText("ÁLBUM")
            b.sub.setText(" · ".join(x for x in (group.subtitle, group.year, count, total) if x))
        elif kind == "artist":
            b.kicker.setText("ARTISTA")
            b.sub.setText(f"{count} · {total}")
        else:
            b.kicker.setText("CARPETA")
            b.sub.setText(f"{count} · {total} · {group.key}")
        b.set_cover(group.cover, kind == "artist", group.name)
        b.title.setText(group.name)
        self._apply_sort(scope=(kind, group.key))
        self.stack.setCurrentWidget(self.songs_page)

    def close_detail(self):
        self.show_page(self.page)

    def _on_search(self, _text=None):
        text = self.banner.search.text()
        self.track_proxy.configure(text=text)
        for proxy in self.grid_proxies:
            proxy.setFilterFixedString(text)

    # ------------------------------------------------------------ orden
    def _sort_context(self) -> str:
        if self.detail:
            return self.detail[0]
        return "nolyrics" if self.page == "nolyrics" else "library"

    def _apply_sort(self, **scope):
        mode, desc = self.sorts[self._sort_context()]
        b = self.banner
        b.sort.setCurrentIndex(next(i for i, (_, m) in enumerate(SORTS) if m == mode))
        b.order.setText(G.SORT_DOWN if desc else G.SORT_UP)
        b.order.setToolTip("Orden descendente (clic para invertir)" if desc
                           else "Orden ascendente (clic para invertir)")
        self.track_proxy.configure(mode=mode, desc=desc, **scope)
        self.songs_header.update()

    def set_sort(self, mode: str, desc: bool | None = None):
        if desc is None:
            desc = mode in DESC_BY_DEFAULT
        self.sorts[self._sort_context()] = (mode, desc)
        self._apply_sort()

    def toggle_order(self):
        mode, desc = self.sorts[self._sort_context()]
        self.set_sort(mode, not desc)

    def _header_sort(self, mode: str):
        current, _ = self.sorts[self._sort_context()]
        if mode == current:
            self.toggle_order()
        else:
            self.set_sort(mode)

    # ------------------------------------------------------------ reproducción
    def play_view(self, shuffle: bool):
        if self.stack.currentWidget() is self.queue_page:
            if self.player.order:
                self.player.set_shuffle(shuffle)
                self.player.jump(0)
            return
        if self.stack.currentWidget() is self.songs_page:
            tracks = self.track_proxy.visible_tracks()
        else:
            tracks = self.library.all()
        if not tracks:
            return
        self.player.set_shuffle(shuffle)
        start = random.randrange(len(tracks)) if shuffle else 0
        self.player.play_list(tracks, start)

    def _play_from_songs(self, idx):
        self.player.play_list(self.track_proxy.visible_tracks(), idx.row())

    def toggle_play(self):
        if not self.player.toggle():
            self.play_view(shuffle=self.player.shuffle)

    def media_key(self, action):
        if action == "toggle":
            self.toggle_play()
        elif action == "next":
            self.player.next()
        elif action == "prev":
            self.player.prev()
        elif action == "stop":
            self.player.mp.pause()

    def change_volume(self, delta):
        self.volume.setValue(self.volume.value() + delta)

    def toggle_mute(self):
        self.player.set_muted(not self.player.muted)
        self.vol_btn.setText(G.MUTE if self.player.muted else G.VOLUME)

    def _on_volume(self, v):
        self.player.set_volume(v / 100)
        if self.player.muted and v > 0:
            self.toggle_mute()

    def _on_seek_release(self):
        self.dragging_seek = False
        self.player.seek(self.seek.value())

    def _on_track(self, t):
        self.state.current_path = t.path
        self.bar_title.setText(t.title)
        self.bar_artist.setText(t.artist_display)
        self.bar_cover.setPixmap(self.covers.get(t.cover, 58, 6, seed=t.album_display))
        self.now_panel.set_track(t)
        self.setWindowTitle(f"{t.title} · {t.artist_display} — Sonora")
        self.seek.setRange(0, int(t.duration * 1000))
        self.dur_lbl.setText(fmt_time(t.duration))
        accent = self.accent_cache.get(t.cover)
        if accent is None:
            accent = self.accent_cache[t.cover] = dominant_color(load_image_small(t.cover, 64))
        self.apply_accent(accent)
        if self.mini:
            self.mini.set_track(t)
        self.songs_view.viewport().update()
        self._load_lyrics(t)

    # ------------------------------------------------------------ letras
    def _load_lyrics(self, t):
        page = self.lyrics_page
        page.set_track(t)
        known, lyr = self.lyrics_service.cached(t.path)
        if known:
            # La canción recién empieza (o se restaurará en pending_seek); position() aún es la anterior.
            shown = with_music_breaks(lyr, t.duration)
            page.set_lyrics(shown, self.player.pending_seek or 0)
            self._set_current_lyrics(shown, "missing", self.player.pending_seek or 0)
        else:
            page.set_loading()
            self._set_current_lyrics(None, "loading", 0)
            self.lyrics_service.request(t)
        page.update()
        self.lyrics_prefetch.start()

    def _set_current_lyrics(self, lyrics, status_if_none: str, position_ms: int):
        """Letra de la canción actual para la tarjeta del panel y el minireproductor."""
        self.current_lyrics = lyrics
        self.lyric_index = None
        self.now_panel.lyrics_card.set_lyrics(lyrics)
        if lyrics is None:
            self.lyric_status = {"loading": "Buscando la letra…", "missing": "Sin letra disponible",
                                 "error": "No se pudo buscar la letra"}[status_if_none]
        elif lyrics.instrumental:
            self.lyric_status = "♪ Instrumental ♪"
        elif not lyrics.synced:
            self.lyric_status = "Letra sin sincronizar"
        else:
            self.lyric_status = ""
        if self.lyric_status and self.mini:
            self.mini.set_lyric_line(self.lyric_status)
        self._update_lyric_line(position_ms)

    def _update_lyric_line(self, ms: int):
        lyr = self.current_lyrics
        if lyr is None or not lyr.synced:
            return
        i = lyr.index_at(ms + LEAD_MS)
        if i == self.lyric_index:
            return
        self.lyric_index = i
        self.now_panel.lyrics_card.set_index(i)
        if self.mini:
            self.mini.set_lyric_line((lyr.lines[i][1] or "♪") if i >= 0 else "♪")

    def _prefetch_lyrics(self):
        """Busca de antemano la letra de la siguiente canción para que aparezca al instante."""
        for t in self.player.upcoming(1):
            if not self.lyrics_service.cached(t.path)[0]:
                self.lyrics_service.request(t)

    def _on_lyrics(self, path, lyrics):
        """Letra lista (búsqueda directa o revisión en segundo plano)."""
        if path != self.state.current_path:
            return
        cur = self.player.current
        shown = with_music_breaks(lyrics, cur.duration if cur else 0.0)
        same = (shown is not None and self.current_lyrics is not None
                and shown.to_dict() == self.current_lyrics.to_dict())
        if same:
            return  # ya se muestra: no reiniciar el desplazamiento
        # Si la canción actual había fallado por el servidor y la revisión la recuperó, aparece sola.
        self.lyrics_service.memory[path] = lyrics
        self.lyrics_page.set_lyrics(shown, self.player.mp.position())
        self._set_current_lyrics(shown, "missing", self.player.mp.position())

    # ------------------------------------------------------------ revisión de letras
    def _lyrics_counts(self) -> dict:
        counts = dict.fromkeys((SYNCED, PLAIN, INSTRUMENTAL, NONE, ERROR, None), 0)
        status_of = self.lyrics_service.status_of
        for path in self.library.tracks:
            s = status_of(path)
            counts[s] = counts.get(s, 0) + 1
        return counts

    def _nolyrics_subtitle(self, counts=None) -> str:
        c = counts or self._lyrics_counts()
        total = len(self.library.tracks)
        checked = total - c[None] - c[ERROR]
        n = c[NONE]
        text = ("Ninguna canción sin letra por ahora" if n == 0 else
                f"{n} canción sin letra" if n == 1 else f"{n} canciones sin letra")
        if checked < total:
            text += f" · revisadas {checked} de {total}"
        return text

    def _on_lyrics_trouble(self, seconds):
        self.lyrics_trouble = seconds
        self._refresh_lyrics_status()

    def _refresh_lyrics_status(self):
        """Actualiza contador, progreso e indicadores (agrupado para no repintar a cada canción)."""
        c = self._lyrics_counts()
        total = len(self.library.tracks)
        checked = total - c[None] - c[ERROR]
        self.nav_buttons["nolyrics"].setText(f"  Sin letra  ({c[NONE]})" if c[NONE] else "  Sin letra")
        if self.lyrics_trouble:
            mins = max(1, round(self.lyrics_trouble / 60))
            pend = f"{c[ERROR]} pendiente" + ("s" if c[ERROR] != 1 else "")
            self.lyrics_label.setText(f"LRCLIB no responde · {pend}, reintento en ~{mins} min")
        elif checked < total:
            self.lyrics_label.setText(f"Revisando letras… {checked} de {total}")
            self._lyrics_done = False
        elif self._lyrics_done is False:
            self.lyrics_label.setText(f"✓ Letras revisadas: {total - c[NONE]} de {total} tienen letra")
            self._lyrics_done = True
            QTimer.singleShot(8000, lambda: self._lyrics_done and self.lyrics_label.setText(""))
        elif self._lyrics_done is None:
            self._lyrics_done = True
        for view in (self.songs_view, self.queue_view):
            if view.isVisible():
                view.viewport().update()
        on_nolyrics = (self.page == "nolyrics" and not self.detail
                       and self.stack.currentWidget() is self.songs_page)
        if on_nolyrics:
            self.banner.sub.setText(self._nolyrics_subtitle(c))
            if c[NONE] != self._last_none:
                self.track_proxy.configure()
        self._last_none = c[NONE]

    def _recheck_lyrics(self, t):
        if t.path == self.state.current_path:
            self.lyrics_page.set_loading()
            self._set_current_lyrics(None, "loading", 0)
        self.lyrics_service.recheck(t)

    def _on_lyrics_failed(self, path, message):
        if path == self.state.current_path:
            self.lyrics_page.set_error(message)
            self._set_current_lyrics(None, "error", 0)

    def _retry_lyrics(self):
        cur = self.player.current
        if cur is not None:
            self.lyrics_page.set_loading()
            self._set_current_lyrics(None, "loading", 0)
            self.lyrics_service.request(cur, force=True)

    def _on_playing(self, playing):
        self.state.playing = playing
        self.play_btn.setText(G.PAUSE if playing else G.PLAY)
        self.play_btn.setToolTip("Pausar (Espacio)" if playing else "Reproducir (Espacio)")
        if playing:
            self.eq_timer.start()
        else:
            self.eq_timer.stop()
            self._tick_eq()
        if self.mini:
            self.mini.set_playing(playing)
        if self.taskbar is not None:
            self.taskbar.set_playing(playing)

    def _on_position(self, ms):
        if not self.dragging_seek:
            self.seek.setValue(ms)
            self.pos_lbl.setText(fmt_time(ms / 1000))
        if self.stack.currentWidget() is self.lyrics_page:
            self.lyrics_page.view.set_position(ms)
        elif self.stack.currentWidget() is self.editor:
            self.editor.on_position(ms)
        self._update_lyric_line(ms)

    def _on_duration(self, ms):
        if ms > 0:
            self.seek.setRange(0, ms)
            self.dur_lbl.setText(fmt_time(ms / 1000))

    def _on_queue(self):
        self.queue_model.set_tracks(self.player.ordered())
        self.now_panel.next_model.set_tracks(self.player.upcoming(8))
        self.lyrics_service.set_priority(self.player.upcoming(15))  # revisar primero lo que va a sonar
        if self.stack.currentWidget() is self.queue_page:
            self.show_page("queue")

    def _scroll_queue(self):
        if 0 <= self.player.pos < self.queue_model.rowCount():
            self.queue_view.scrollTo(self.queue_model.index(self.player.pos, 0),
                                     QAbstractItemView.ScrollHint.PositionAtTop)

    def _sync_modes(self):
        set_active(self.shuffle_btn, self.player.shuffle)
        set_active(self.repeat_btn, self.player.repeat != REPEAT_OFF)
        self.repeat_btn.setText(G.REPEAT_ONE if self.player.repeat == REPEAT_ONE else G.REPEAT_ALL)
        self.repeat_btn.setToolTip(["Repetir: desactivado", "Repetir: todo", "Repetir: una"][self.player.repeat])

    def _tick_eq(self):
        """Anima el ecualizador repintando sólo la fila que suena, no toda la lista."""
        self.state.phase += 0.35
        for view, model in ((self.songs_view, self.track_proxy), (self.queue_view, self.queue_model)):
            if view.isVisible():
                row = model.row_of(self.state.current_path)
                if row is not None:
                    view.viewport().update(view.visualRect(model.index(row, 0)))

    def apply_accent(self, color: QColor):
        if QColor(color) == self.state.accent and self._accent_applied:
            return
        self._accent_applied = True
        self.state.accent = QColor(color)
        qss = accent_qss(self.state.accent)
        for w in (self.banner, self.player_bar, self.mini, self.editor):
            if w is not None:
                w.setStyleSheet(qss)
        self.banner.update()
        self.now_panel.update()
        self.songs_view.viewport().update()
        if self.mini:
            self.mini.update()

    # ------------------------------------------------------------ menú contextual
    def _track_menu(self, view, pos):
        idx = view.indexAt(pos)
        if not idx.isValid():
            return
        t = idx.data(TRACK_ROLE)
        m = QMenu(self)
        m.addAction("Reproducir", lambda: view.doubleClicked.emit(idx))
        m.addAction("Reproducir a continuación", lambda: self.player.play_next([t]))
        m.addAction("Agregar a la cola", lambda: self.player.enqueue([t]))
        m.addSeparator()
        album = self._find_group("album", t.album_key)
        if album:
            m.addAction("Ir al álbum", lambda: self.open_detail("album", album))
        artist = next((g for g in self.artists if g.name.lower() == t.artists[0].lower()), None)
        if artist:
            m.addAction("Ir al artista", lambda: self.open_detail("artist", artist))
        folder = self._find_group("folder", os.path.dirname(t.path))
        if folder:
            m.addAction("Ir a la carpeta", lambda: self.open_detail("folder", folder))
        m.addAction("Agregar o editar letra…", lambda: self.open_editor(t))
        m.addAction("Buscar la letra de nuevo", lambda: self._recheck_lyrics(t))
        m.addAction("Mostrar en el Explorador", lambda: subprocess.Popen(f'explorer /select,"{t.path}"'))
        m.exec(view.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------ minireproductor
    def show_mini(self):
        if self.mini is None:
            self.mini = MiniPlayer(self)
            self.mini.setStyleSheet(accent_qss(self.state.accent))
            self.mini.expandRequested.connect(self.hide_mini)
            self.mini.lyricsModeChanged.connect(lambda on: self.settings.setValue("mini_lyrics", on))
            self.mini.set_lyrics_mode(self.settings.value("mini_lyrics", True, type=bool))
            pos = self.settings.value("mini_pos")
            self.mini.place(pos if isinstance(pos, QPoint) else None)
        self.mini.set_track(self.player.current)
        self.mini.set_playing(self.player.is_playing())
        self.mini.sync_modes()
        if self.lyric_status:
            self.mini.set_lyric_line(self.lyric_status)
        else:
            self.lyric_index = None
            self._update_lyric_line(self.player.mp.position())
        self.mini.show()
        self.mini.raise_()
        if self.taskbar is not None:
            self.taskbar.attach(int(self.mini.winId()))
        self.hide()

    def hide_mini(self):
        if self.mini:
            self.settings.setValue("mini_pos", self.mini.pos())
            self.mini.hide()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    # ------------------------------------------------------------ arrastrar y soltar
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.open_paths([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])

    # ------------------------------------------------------------ ciclo de vida
    def showEvent(self, e):
        super().showEvent(e)
        if self.media_keys is None:
            dark_title_bar(self)
            try:
                self.media_keys = MediaKeys(int(self.winId()), self.media_key)
                QApplication.instance().installNativeEventFilter(self.media_keys)
            except Exception:
                self.media_keys = None
        if self.taskbar is None:
            try:
                self.taskbar = TaskbarButtons(self.media_key)
                self.taskbar.set_playing(self.player.is_playing())
            except Exception:
                self.taskbar = None
        if self.taskbar is not None:
            self.taskbar.attach(int(self.winId()))

    def _restore_settings(self):
        s = self.settings
        geo = s.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        self.volume.setValue(s.value("volume", 70, type=int))
        self.player.shuffle = s.value("shuffle", False, type=bool)
        self.player.repeat = s.value("repeat", 0, type=int)
        self.now_panel.setVisible(s.value("now_panel", True, type=bool))
        try:
            saved = json.loads(s.value("sorts", "{}"))
        except (TypeError, ValueError):
            saved = {}
        for ctx, value in saved.items():
            if ctx in self.sorts and isinstance(value, list) and len(value) == 2 and value[0] in SORT_MODES:
                self.sorts[ctx] = (value[0], bool(value[1]))
        self._sync_modes()

    def _restore_last_track(self):
        last = self.settings.value("last_path", "")
        if last and last in self.library.tracks:
            tracks = self.track_proxy.visible_tracks()
            idx = next((i for i, t in enumerate(tracks) if t.path == last), 0)
            self.player.pending_seek = self.settings.value("last_pos", 0, type=int) or None
            self.player.play_list(tracks, idx, play=False)

    def closeEvent(self, e):
        s = self.settings
        s.setValue("geometry", self.saveGeometry())
        s.setValue("volume", self.volume.value())
        s.setValue("shuffle", self.player.shuffle)
        s.setValue("repeat", self.player.repeat)
        s.setValue("now_panel", self.now_panel.isVisible())
        s.setValue("sorts", json.dumps(self.sorts))
        cur = self.player.current
        s.setValue("last_path", cur.path if cur else "")
        s.setValue("last_pos", self.player.mp.position())
        if self.mini:
            s.setValue("mini_pos", self.mini.pos())
            self.mini.close()
        if self.scanner is not None:
            self.scanner.requestInterruption()
            self.scanner.wait(3000)
        if self.media_keys:
            self.media_keys.unregister()
        self.player.mp.stop()
        self.lyrics_service.stop()
        self.library.save()
        super().closeEvent(e)
        QApplication.instance().quit()
