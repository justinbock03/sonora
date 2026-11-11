"""Pantalla de letras: línea actual resaltada, desplazamiento automático y clic para saltar."""
import time

from PySide6.QtCore import QEasingCurve, QRect, QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .theme import UI_FONT, G
from .widgets import ElidedLabel, icon_button, wrap_lines

MARGIN = 44
FOLLOW_PAUSE = 4.0     # segundos sin seguir la canción tras desplazar con la rueda
LEAD_MS = 250          # resaltar la línea un instante antes de que se cante
ANCHOR = 0.38          # la línea actual se mantiene a este % de la altura


def _font(px: int, weight=QFont.Weight.Bold) -> QFont:
    f = QFont(UI_FONT)
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


def lyrics_colors(accent: QColor) -> tuple[QColor, QColor]:
    """Fondo oscuro teñido con el color de la canción (legible con texto blanco)."""
    h = max(accent.hsvHue(), 0)
    s = min(accent.hsvSaturation(), 190)
    return QColor.fromHsv(h, s, 112), QColor.fromHsv(h, min(s + 20, 255), 34)


class LyricsView(QWidget):
    seekRequested = Signal(int)

    def __init__(self):
        super().__init__()
        self.lyrics = None
        self.message, self.detail = "", ""
        self.index = -1
        self.hover = -1
        self.offset = 0.0
        self.follow_paused_until = 0.0
        self._cache = None   # (ancho, rects, alto total)
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(450)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.valueChanged.connect(self._on_anim)
        self.setMouseTracking(True)

    # ------------------------------------------------------------ datos
    @property
    def synced(self) -> bool:
        return bool(self.lyrics and self.lyrics.synced)

    def texts(self) -> list[str]:
        if not self.lyrics:
            return []
        if self.lyrics.synced:
            return [t or "♪" for _, t in self.lyrics.lines]
        return self.lyrics.plain.split("\n")

    def show_message(self, message: str, detail: str = ""):
        self.lyrics, self.message, self.detail = None, message, detail
        self._reset()

    def set_lyrics(self, lyrics):
        self.lyrics, self.message, self.detail = lyrics, "", ""
        self._reset()

    def _reset(self):
        self.anim.stop()
        self.index = -1
        self.hover = -1
        self._cache = None
        self.follow_paused_until = 0.0
        self.offset = self._target(-1) if self.synced else -24.0
        self.update()

    def set_position(self, ms: int, snap: bool = False):
        if not self.synced:
            return
        i = self.lyrics.index_at(ms + LEAD_MS)
        if i == self.index and not snap:
            return
        self.index = i
        if snap:
            self.anim.stop()
            self.follow_paused_until = 0.0
            self.offset = self._target(i)
        elif time.monotonic() >= self.follow_paused_until:
            self._scroll_to(self._target(i))
        self.update()

    # ------------------------------------------------------------ geometría
    def _line_font(self) -> QFont:
        return _font(30) if self.synced else _font(20, QFont.Weight.DemiBold)

    def _layout(self):
        w = self.width()
        if self._cache and self._cache[0] == w:
            return self._cache[1], self._cache[2]
        fm = QFontMetrics(self._line_font())
        tw = max(100, w - 2 * MARGIN)
        rects, y = [], 0.0
        gap = 20 if self.synced else 6
        for text in self.texts():
            if not text.strip() and not self.synced:
                rects.append(QRectF(MARGIN, y, tw, 0))
                y += 22
                continue
            h = fm.boundingRect(QRect(0, 0, tw, 100000), Qt.TextFlag.TextWordWrap, text).height()
            rects.append(QRectF(MARGIN, y, tw, h))
            y += h + gap
        self._cache = (w, rects, y)
        return rects, y

    def _target(self, i: int) -> float:
        rects, _ = self._layout()
        if not rects:
            return 0.0
        anchor = rects[0].top() if i < 0 else rects[min(i, len(rects) - 1)].center().y()
        return anchor - self.height() * ANCHOR

    def _clamp(self, value: float) -> float:
        _, total = self._layout()
        if self.synced:
            return max(-self.height() * ANCHOR, min(value, total - self.height() * ANCHOR))
        return max(-24.0, min(value, max(-24.0, total - self.height() + 60)))

    def _scroll_to(self, target: float):
        self.anim.stop()
        self.anim.setStartValue(float(self.offset))
        self.anim.setEndValue(float(target))
        self.anim.start()

    def _on_anim(self, value):
        self.offset = float(value)
        self.update()

    def _line_at(self, y: float) -> int:
        rects, _ = self._layout()
        y += self.offset
        for i, r in enumerate(rects):
            if r.top() - 10 <= y <= r.bottom() + 10:
                return i
        return -1

    # ------------------------------------------------------------ pintura
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        if self.lyrics is None or self.lyrics.instrumental:
            msg = "♪  Instrumental  ♪" if self.lyrics is not None else self.message
            p.setFont(_font(26))
            p.setPen(QColor(255, 255, 255, 230))
            r = QRect(MARGIN, 0, self.width() - 2 * MARGIN, int(self.height() * 0.5))
            p.drawText(r, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom | Qt.TextFlag.TextWordWrap, msg)
            if self.detail:
                p.setFont(_font(14, QFont.Weight.Normal))
                p.setPen(QColor(255, 255, 255, 160))
                r2 = QRect(MARGIN, int(self.height() * 0.5) + 10, self.width() - 2 * MARGIN, 60)
                p.drawText(r2, Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap, self.detail)
            return
        # Se pinta en una capa aparte para desvanecer los bordes superior e inferior.
        dpr = self.devicePixelRatioF()
        layer = QPixmap(int(self.width() * dpr), int(self.height() * dpr))
        layer.setDevicePixelRatio(dpr)
        layer.fill(Qt.GlobalColor.transparent)
        lp = QPainter(layer)
        lp.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        self._paint_lines(lp)
        fade = min(56, self.height() // 6)
        mask = QLinearGradient(0, 0, 0, self.height())
        edge = fade / max(1, self.height())
        mask.setColorAt(0, QColor(0, 0, 0, 0))
        mask.setColorAt(edge, QColor(0, 0, 0, 255))
        mask.setColorAt(1 - edge, QColor(0, 0, 0, 255))
        mask.setColorAt(1, QColor(0, 0, 0, 0))
        lp.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        lp.fillRect(self.rect(), mask)
        lp.end()
        p.drawPixmap(0, 0, layer)

    def _paint_lines(self, p: QPainter):
        rects, _ = self._layout()
        p.setFont(self._line_font())
        texts = self.texts()
        h = self.height()
        for i, (text, r) in enumerate(zip(texts, rects)):
            rr = r.translated(0, -self.offset)
            if rr.bottom() < -40 or rr.top() > h + 40 or not text.strip():
                continue
            if not self.synced:
                color = QColor(255, 255, 255, 225)
            elif i == self.index:
                color = QColor(255, 255, 255)
            elif i < self.index:
                color = QColor(255, 255, 255, 135)
            else:
                color = QColor(255, 255, 255, 80)
            if self.synced and i == self.hover and i != self.index:
                color.setAlpha(min(255, color.alpha() + 70))
            p.setPen(color)
            p.drawText(rr, Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, text)

    # ------------------------------------------------------------ interacción
    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._cache = None
        self.anim.stop()
        self.offset = self._clamp(self._target(self.index) if self.synced else self.offset)

    def wheelEvent(self, e):
        if self.lyrics is None:
            return
        self.anim.stop()
        self.offset = self._clamp(self.offset - e.angleDelta().y() * 0.7)
        self.follow_paused_until = time.monotonic() + FOLLOW_PAUSE
        self.update()

    def mouseMoveEvent(self, e):
        if not self.synced:
            return
        i = self._line_at(e.position().y())
        if i != self.hover:
            self.hover = i
            self.setCursor(Qt.CursorShape.PointingHandCursor if i >= 0 else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, e):
        if self.hover != -1:
            self.hover = -1
            self.update()

    def mousePressEvent(self, e):
        if self.synced and e.button() == Qt.MouseButton.LeftButton:
            i = self._line_at(e.position().y())
            if i >= 0:
                self.follow_paused_until = 0.0
                self.seekRequested.emit(self.lyrics.lines[i][0])


class LyricsCard(QWidget):
    """Tarjeta «Letra» del panel derecho: la línea actual y las dos siguientes."""
    clicked = Signal()
    ROWS = 3

    def __init__(self, state):
        super().__init__()
        self.state = state
        self.lyrics = None
        self.index = -1
        self.hovered = False
        self.setFixedHeight(136)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Ver la letra completa (Ctrl+L)")
        self.hide()

    def set_lyrics(self, lyrics):
        self.lyrics = lyrics
        self.index = -1
        has_text = lyrics is not None and not lyrics.instrumental and bool(lyrics.lines or lyrics.plain.strip())
        self.setVisible(has_text)
        self.update()

    def set_index(self, i: int):
        if i != self.index:
            self.index = i
            self.update()

    def _rows(self):
        if self.lyrics.synced:
            texts = [t or "♪" for _, t in self.lyrics.lines]
            start = max(self.index, 0)
            rows = texts[start:start + self.ROWS]
            first_alpha = 255 if self.index >= 0 else 150
            return [(t, first_alpha if k == 0 else 115) for k, t in enumerate(rows)]
        lines = [t for t in self.lyrics.plain.split("\n") if t.strip()]
        return [(t, 215) for t in lines[:self.ROWS]]

    def paintEvent(self, _):
        if self.lyrics is None:
            return
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        top, bottom = lyrics_colors(self.state.accent)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0, top.lighter(118) if self.hovered else top)
        g.setColorAt(1, bottom)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 10, 10)
        p.fillPath(path, g)

        w = self.width() - 32
        p.setFont(_font(13))
        p.setPen(QColor(255, 255, 255))
        head = "Letra" if self.lyrics.synced else "Letra · sin sincronizar"
        p.drawText(QRect(16, 12, w, 20), Qt.AlignmentFlag.AlignVCenter, head)
        p.setFont(_font(16))
        fm = p.fontMetrics()
        visual = []
        for k, (text, alpha) in enumerate(self._rows()):
            if k == 0 and self.lyrics.synced:   # la línea actual puede usar 2 renglones
                visual += [(part, alpha) for part in wrap_lines(text, fm, w, 2)]
            else:
                visual.append((fm.elidedText(text, Qt.TextElideMode.ElideRight, w), alpha))
        y = 40
        for text, alpha in visual[:self.ROWS]:
            p.setPen(QColor(255, 255, 255, alpha))
            p.drawText(QRect(16, y, w, 26), Qt.AlignmentFlag.AlignVCenter, text)
            y += 28

    def enterEvent(self, e):
        self.hovered = True
        self.update()

    def leaveEvent(self, e):
        self.hovered = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


class LyricsPage(QWidget):
    closeRequested = Signal()
    retryRequested = Signal()
    editRequested = Signal()

    def __init__(self, state, covers):
        super().__init__()
        self.state, self.covers = state, covers
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 12)
        lay.setSpacing(0)

        head = QHBoxLayout()
        head.setContentsMargins(28, 22, 22, 14)
        head.setSpacing(14)
        self.cover = QLabel()
        self.cover.setFixedSize(64, 64)
        head.addWidget(self.cover)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addStretch(1)
        self.title = ElidedLabel("", "lyricsTitle")
        self.artist = ElidedLabel("", "lyricsArtist")
        col.addWidget(self.title)
        col.addWidget(self.artist)
        col.addStretch(1)
        head.addLayout(col, 1)
        self.source = QLabel("")
        self.source.setObjectName("lyricsSource")
        head.addWidget(self.source, 0, Qt.AlignmentFlag.AlignVCenter)
        self.edit_btn = QPushButton("Agregar letra")
        self.edit_btn.setObjectName("lyricsPill")
        self.edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.edit_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.edit_btn.hide()
        head.addWidget(self.edit_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self.retry = icon_button(G.REFRESH, "Buscar la letra de nuevo", "lyricsBtn", 34)
        self.close_btn = icon_button(G.CLOSE, "Cerrar letra (Ctrl+L)", "lyricsBtn", 34)
        head.addWidget(self.retry)
        head.addWidget(self.close_btn)
        lay.addLayout(head)

        self.view = LyricsView()
        lay.addWidget(self.view, 1)
        self.retry.clicked.connect(self.retryRequested)
        self.close_btn.clicked.connect(self.closeRequested)
        self.edit_btn.clicked.connect(self.editRequested)
        self.set_track(None)

    def _edit_label(self, text: str | None):
        self.edit_btn.setVisible(text is not None)
        if text:
            self.edit_btn.setText(text)

    def set_track(self, t):
        if t is None:
            self._edit_label(None)
            self.cover.clear()
            self.title.setText("Letra")
            self.artist.setText("")
            self.source.setText("")
            self.view.show_message("Reproduce una canción para ver su letra")
            return
        self.cover.setPixmap(self.covers.get(t.cover, 64, 8, seed=t.album_display))
        self.title.setText(t.title)
        self.artist.setText(t.artist_display)

    def set_loading(self):
        self.source.setText("")
        self._edit_label(None)
        self.view.show_message("Buscando la letra…")

    def set_lyrics(self, lyrics, position_ms: int):
        if lyrics is None:
            self.source.setText("")
            self._edit_label("Agregar letra")
            self.view.show_message("No encontramos la letra de esta canción",
                                   "Pulsa «Agregar letra» para escribirla o pegarla y sincronizarla tú mismo.")
            return
        extra = "" if lyrics.synced or lyrics.instrumental else " · sin sincronizar"
        self.source.setText(f"Fuente: {lyrics.source}{extra}")
        self._edit_label("Editar letra" if lyrics.synced or lyrics.instrumental else "Sincronizar letra")
        self.view.set_lyrics(lyrics)
        self.view.set_position(position_ms, snap=True)

    def set_error(self, message: str):
        self.source.setText("")
        self._edit_label("Agregar letra")
        self.view.show_message("No se pudo buscar la letra", f"{message}. Pulsa ⟳ para reintentar.")

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        top, bottom = lyrics_colors(self.state.accent)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0, top)
        g.setColorAt(1, bottom)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 12, 12)
        p.fillPath(path, g)
