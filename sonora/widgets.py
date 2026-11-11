"""Widgets reutilizables, caché de carátulas e integración con Windows."""
import ctypes
import os
import zlib
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QBuffer, QIODevice, QRectF, QSize, Qt
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QImageReader, QLinearGradient,
                           QPainter, QPainterPath, QPixmap)
from PySide6.QtWidgets import QLabel, QSizePolicy, QSlider, QStyle, QStyleOptionSlider, QToolButton

from .theme import ICON_FONT, G, glyph_pixmap


def fmt_time(sec) -> str:
    sec = int(sec or 0)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_total(sec) -> str:
    m = int(sec or 0) // 60
    h, m = divmod(m, 60)
    return f"{h} h {m} min" if h else f"{m} min"


def icon_button(glyph: str, tip: str = "", name: str = "iconBtn", size: int = 32) -> QToolButton:
    b = QToolButton()
    b.setObjectName(name)
    b.setText(glyph)
    b.setToolTip(tip)
    b.setFixedSize(size, size)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return b


def set_active(widget, on: bool):
    widget.setProperty("active", "true" if on else "false")
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class ElidedLabel(QLabel):
    """QLabel que recorta el texto con «…» en lugar de ensancharse."""

    def __init__(self, text: str = "", name: str = ""):
        super().__init__()
        if name:
            self.setObjectName(name)
        self._full = text
        self.setMinimumWidth(10)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._refresh()

    def setText(self, text: str):
        self._full = text or ""
        self._refresh()

    def text(self) -> str:
        return self._full

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._refresh()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() in (e.Type.FontChange, e.Type.StyleChange):
            self._refresh()

    def _refresh(self):
        shown = self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, max(self.width(), 10))
        super().setText(shown)
        self.setToolTip(self._full if shown != self._full else "")


def wrap_lines(text: str, fm, width: int, max_lines: int = 2) -> list[str]:
    """Reparte `text` en hasta `max_lines` renglones; sólo el último se recorta con «…»."""
    words = text.split()
    lines, cur = [], ""
    for idx, w in enumerate(words):
        test = f"{cur} {w}" if cur else w
        if cur and fm.horizontalAdvance(test) > width:
            lines.append(cur)
            if len(lines) == max_lines - 1:
                rest = " ".join(words[idx:])
                lines.append(fm.elidedText(rest, Qt.TextElideMode.ElideRight, width))
                return lines
            cur = w
        else:
            cur = test
    if cur:
        lines.append(fm.elidedText(cur, Qt.TextElideMode.ElideRight, width))
    return lines or [""]


class WrapLabel(QLabel):
    """Etiqueta de alto fijo que usa hasta N renglones antes de recortar con «…»."""

    def __init__(self, text: str = "", name: str = "", max_lines: int = 2):
        super().__init__()
        if name:
            self.setObjectName(name)
        self._full = text
        self.max_lines = max_lines
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._refresh()

    def setText(self, text: str):
        self._full = text or ""
        self._refresh()

    def text(self) -> str:
        return self._full

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._refresh()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() in (e.Type.FontChange, e.Type.StyleChange):
            self._refresh()

    def _refresh(self):
        fm = self.fontMetrics()
        self.setFixedHeight(fm.lineSpacing() * self.max_lines + 2)
        lines = wrap_lines(self._full, fm, max(self.width(), 10), self.max_lines)
        shown = "\n".join(lines)
        super().setText(shown)
        self.setToolTip(self._full if shown.replace("\n", " ") != self._full else "")


class ClickSlider(QSlider):
    """Slider que salta a la posición donde se hace clic."""

    def __init__(self, wheel: bool = True):
        super().__init__(Qt.Orientation.Horizontal)
        self._wheel = wheel
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.maximum() > self.minimum():
            opt = QStyleOptionSlider()
            self.initStyleOption(opt)
            handle = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, opt,
                                                 QStyle.SubControl.SC_SliderHandle, self)
            if not handle.contains(e.position().toPoint()):
                hw = handle.width()
                self.setValue(QStyle.sliderValueFromPosition(
                    self.minimum(), self.maximum(), int(e.position().x() - hw / 2), self.width() - hw))
        super().mousePressEvent(e)

    def wheelEvent(self, e):
        if self._wheel:
            super().wheelEvent(e)
        else:
            e.ignore()


class Covers:
    """Genera y guarda en memoria miniaturas redondeadas de carátulas."""

    def __init__(self):
        self.cache: dict = {}
        self.dpr = QGuiApplication.primaryScreen().devicePixelRatio()

    def get(self, path: str, size: int, radius: float = 6, circle: bool = False, seed: str = "") -> QPixmap:
        key = (path, size, radius, circle, "" if path else seed)
        pm = self.cache.get(key)
        if pm is None:
            if len(self.cache) > 4000:
                self.cache.clear()
            pm = self.cache[key] = self._make(path, size, radius, circle, seed)
        return pm

    def _make(self, path, size, radius, circle, seed) -> QPixmap:
        px = max(1, round(size * self.dpr))
        out = QPixmap(px, px)
        out.setDevicePixelRatio(self.dpr)
        out.fill(Qt.GlobalColor.transparent)
        p = QPainter(out)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(0, 0, size, size)
        clip = QPainterPath()
        if circle:
            clip.addEllipse(rect)
        else:
            clip.addRoundedRect(rect, radius, radius)
        p.setClipPath(clip)
        img = None
        if path and os.path.exists(path):
            reader = QImageReader(path)
            reader.setAutoTransform(True)
            src = reader.size()
            if src.isValid() and src.width() > 0 and src.height() > 0:
                scale = max(px / src.width(), px / src.height())
                reader.setScaledSize(QSize(max(px, round(src.width() * scale)), max(px, round(src.height() * scale))))
            img = reader.read()
        if img is not None and not img.isNull():
            sx, sy = (img.width() - px) / 2, (img.height() - px) / 2
            p.drawImage(rect, img, QRectF(sx, sy, px, px))
        else:
            hue = zlib.crc32(seed.encode("utf-8")) % 360
            g = QLinearGradient(0, 0, size, size)
            g.setColorAt(0, QColor.fromHsv(hue, 110, 120))
            g.setColorAt(1, QColor.fromHsv((hue + 50) % 360, 150, 55))
            p.fillRect(rect, g)
            f = QFont(ICON_FONT)
            f.setPixelSize(max(8, int(size * 0.36)))
            p.setFont(f)
            p.setPen(QColor(255, 255, 255, 150))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, G.NOTE)
        p.end()
        return out


def load_image_small(path: str, size: int = 64):
    """Carga una versión reducida de una imagen (rápido, para colores y fondos)."""
    if not path or not os.path.exists(path):
        return None
    reader = QImageReader(path)
    reader.setScaledSize(QSize(size, size))
    img = reader.read()
    return None if img.isNull() else img


# ---------------------------------------------------------------- Windows

def dark_title_bar(widget):
    try:
        hwnd = int(widget.winId())
        value = ctypes.c_int(1)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (nuevo y antiguo)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), 4) == 0:
                break
    except Exception:
        pass


WM_HOTKEY = 0x0312
MEDIA_KEYS = {0xB3: "toggle", 0xB0: "next", 0xB1: "prev", 0xB2: "stop"}


class MediaKeys(QAbstractNativeEventFilter):
    """Teclas multimedia globales (Play/Pausa, Siguiente, Anterior, Stop)."""

    def __init__(self, hwnd: int, callback):
        super().__init__()
        self.hwnd = hwnd
        self.callback = callback
        self.ids = []
        user32 = ctypes.windll.user32
        for i, vk in enumerate(MEDIA_KEYS, start=0xB500):
            if user32.RegisterHotKey(wintypes.HWND(hwnd), i, 0x4000, vk):  # MOD_NOREPEAT
                self.ids.append((i, vk))

    def unregister(self):
        for i, _ in self.ids:
            ctypes.windll.user32.UnregisterHotKey(wintypes.HWND(self.hwnd), i)
        self.ids = []

    def nativeEventFilter(self, event_type, message):
        try:
            if bytes(event_type) == b"windows_generic_MSG":
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY:
                    vk = (msg.lParam >> 16) & 0xFFFF
                    action = MEDIA_KEYS.get(vk)
                    if action:
                        self.callback(action)
                        return True, 0
        except Exception:
            pass
        return False, 0


# ---------------------------------------------------------------- barra de tareas

class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, text: str) -> "_GUID":
        g = cls()
        ctypes.windll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(g))
        return g


class _THUMBBUTTON(ctypes.Structure):
    _fields_ = [("dwMask", wintypes.DWORD), ("iId", wintypes.UINT), ("iBitmap", wintypes.UINT),
                ("hIcon", wintypes.HICON), ("szTip", ctypes.c_wchar * 260), ("dwFlags", wintypes.DWORD)]


WM_COMMAND = 0x0111
THBN_CLICKED = 0x1800
THB_ICON, THB_TOOLTIP, THB_FLAGS = 0x2, 0x4, 0x8
SM_CXSMICON = 49


_SUBCLASSPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                  wintypes.LPARAM, ctypes.c_size_t, ctypes.c_size_t)


class TaskbarButtons:
    """Botones Anterior / Reproducir-Pausa / Siguiente en la miniatura de la barra de tareas.

    Usa ITaskbarList3 directamente por COM (Qt 6 ya no incluye QWinThumbnailToolbar).
    Los clics llegan como WM_COMMAND *enviado* a la ventana, que Qt no pasa a los filtros
    nativos, así que se subclasifica la ventana con SetWindowSubclass para verlos.
    """
    BUTTONS = {1: "prev", 2: "toggle", 3: "next"}

    def __init__(self, callback):
        self.callback = callback
        self._proc = _SUBCLASSPROC(self._wndproc)  # referencia viva mientras exista la ventana
        comctl = ctypes.windll.comctl32
        self._set_subclass = comctl.SetWindowSubclass
        self._set_subclass.argtypes = [wintypes.HWND, _SUBCLASSPROC, ctypes.c_size_t, ctypes.c_size_t]
        self._def_proc = comctl.DefSubclassProc
        self._def_proc.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self._def_proc.restype = ctypes.c_ssize_t
        self.hwnds: set[int] = set()
        self.added: set[int] = set()
        self.playing = False
        user32 = ctypes.windll.user32
        self.msg_created = user32.RegisterWindowMessageW("TaskbarButtonCreated")
        self.size = user32.GetSystemMetrics(SM_CXSMICON) or 16
        self.icons = {name: self._make_icon(glyph) for name, glyph in
                      (("prev", G.PREV), ("play", G.PLAY), ("pause", G.PAUSE), ("next", G.NEXT))}
        self.tbl = self._create_taskbar_list()

    # -------------------------------------------------------- COM
    def _create_taskbar_list(self):
        ole32 = ctypes.windll.ole32
        ole32.CoInitialize(None)
        ptr = ctypes.c_void_p()
        clsid = _GUID.parse("{56FDF344-FD6D-11d0-958A-006097C9A090}")  # CLSID_TaskbarList
        iid = _GUID.parse("{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF}")    # IID_ITaskbarList3
        if ole32.CoCreateInstance(ctypes.byref(clsid), None, 1, ctypes.byref(iid), ctypes.byref(ptr)) != 0:
            return None
        self._ptr = ptr
        if self._call(3, ctypes.HRESULT) != 0:  # HrInit
            return None
        return ptr

    def _call(self, index, restype, *args, argtypes=()):
        vtable = ctypes.cast(self._ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
        return proto(vtable[index])(self._ptr, *args)

    def _make_icon(self, glyph: str):
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        glyph_pixmap(glyph, "#ffffff", self.size, dpr=1.0).save(buf, "PNG")
        data = bytes(buf.data())
        fn = ctypes.windll.user32.CreateIconFromResourceEx
        fn.restype = wintypes.HICON
        fn.argtypes = [ctypes.c_char_p, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD,
                       ctypes.c_int, ctypes.c_int, wintypes.UINT]
        return fn(data, len(data), True, 0x00030000, self.size, self.size, 0)

    def _buttons(self):
        arr = (_THUMBBUTTON * 3)()
        specs = ((1, "prev", "Anterior"),
                 (2, "pause" if self.playing else "play", "Pausar" if self.playing else "Reproducir"),
                 (3, "next", "Siguiente"))
        for b, (bid, icon, tip) in zip(arr, specs):
            b.dwMask = THB_ICON | THB_TOOLTIP | THB_FLAGS
            b.iId = bid
            b.hIcon = self.icons[icon]
            b.szTip = tip
            b.dwFlags = 0  # THBF_ENABLED
        return arr

    # -------------------------------------------------------- API
    def attach(self, hwnd: int):
        """Agrega los botones a la ventana (o en cuanto Windows cree su botón en la barra)."""
        if hwnd not in self.hwnds:
            self.hwnds.add(hwnd)
            self._set_subclass(hwnd, self._proc, 0x50AA, 0)
        self._add(hwnd)

    def _add(self, hwnd: int):
        if self.tbl is None or hwnd in self.added:
            return
        arr = self._buttons()
        hr = self._call(15, ctypes.HRESULT, wintypes.HWND(hwnd), 3, arr,  # ThumbBarAddButtons
                        argtypes=(wintypes.HWND, wintypes.UINT, ctypes.POINTER(_THUMBBUTTON)))
        if hr == 0:
            self.added.add(hwnd)

    def set_playing(self, playing: bool):
        self.playing = playing
        if self.tbl is None:
            return
        for hwnd in self.added:
            arr = self._buttons()
            self._call(16, ctypes.HRESULT, wintypes.HWND(hwnd), 3, arr,  # ThumbBarUpdateButtons
                       argtypes=(wintypes.HWND, wintypes.UINT, ctypes.POINTER(_THUMBBUTTON)))

    def _wndproc(self, hwnd, msg, wparam, lparam, _id, _ref):
        try:
            if msg == self.msg_created:
                # Windows (re)creó el botón de la barra: al volver a mostrar la ventana
                # o si se reinició el Explorador. Hay que volver a agregar los botones.
                self.added.discard(hwnd)
                self._add(hwnd)
            elif msg == WM_COMMAND and (wparam >> 16) & 0xFFFF == THBN_CLICKED:
                action = self.BUTTONS.get(wparam & 0xFFFF)
                if action:
                    self.callback(action)
                    return 0
        except Exception:
            pass
        return self._def_proc(hwnd, msg, wparam, lparam)
