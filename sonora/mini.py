"""Minireproductor flotante: siempre visible, con fondo difuminado de la carátula."""
from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .player import REPEAT_OFF, REPEAT_ONE
from .theme import G
from .widgets import ElidedLabel, WrapLabel, fmt_time, icon_button, load_image_small, set_active

M = 16          # margen para la sombra
CARD_W, CARD_H = 400, 132
LYRIC_H = 42    # alto extra cuando se muestra la letra (hasta 2 renglones)
RADIUS = 20


class MiniPlayer(QWidget):
    expandRequested = Signal()
    lyricsModeChanged = Signal(bool)

    def __init__(self, win):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.win, self.player, self.covers, self.state = win, win.player, win.covers, win.state
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("Sonora")
        self.setWindowIcon(win.windowIcon())
        self.setFixedSize(CARD_W + 2 * M, CARD_H + 2 * M)
        self.bg = None
        self.lyrics_mode = False

        lay = QHBoxLayout(self)
        lay.setContentsMargins(M + 14, M + 14, M + 12, M + 20)
        lay.setSpacing(14)
        self.cover = QLabel()
        self.cover.setFixedSize(92, 92)
        lay.addWidget(self.cover, 0, Qt.AlignmentFlag.AlignVCenter)

        col = QVBoxLayout()
        col.setSpacing(0)
        top = QHBoxLayout()
        top.setSpacing(2)
        texts = QVBoxLayout()
        texts.setSpacing(0)
        self.title = ElidedLabel("Sonora", "miniTitle")
        self.artist = ElidedLabel("Nada en reproducción", "miniArtist")
        texts.addWidget(self.title)
        texts.addWidget(self.artist)
        top.addLayout(texts, 1)
        self.lyrics_btn = icon_button(G.LYRICS, "Mostrar la letra", "miniSmall", 24)
        self.expand_btn = icon_button(G.EXPAND, "Abrir Sonora", "miniSmall", 24)
        self.close_btn = icon_button(G.CLOSE, "Cerrar minireproductor", "miniSmall", 24)
        for b in (self.lyrics_btn, self.expand_btn, self.close_btn):
            top.addWidget(b, 0, Qt.AlignmentFlag.AlignTop)
        col.addLayout(top)
        self.lyric = WrapLabel("", "miniLyric", max_lines=2)
        self.lyric.hide()
        col.addSpacing(2)
        col.addWidget(self.lyric)
        col.addStretch(1)

        ctr = QHBoxLayout()
        ctr.setSpacing(6)
        self.shuffle_btn = icon_button(G.SHUFFLE, "Aleatorio", "miniBtn", 30)
        self.prev_btn = icon_button(G.PREV, "Anterior", "miniBtn", 30)
        self.play_btn = icon_button(G.PLAY, "Reproducir", "miniPlay", 38)
        self.next_btn = icon_button(G.NEXT, "Siguiente", "miniBtn", 30)
        self.repeat_btn = icon_button(G.REPEAT_ALL, "Repetir", "miniBtn", 30)
        for b in (self.shuffle_btn, self.prev_btn, self.play_btn, self.next_btn, self.repeat_btn):
            ctr.addWidget(b)
        ctr.addStretch(1)
        self.time_lbl = QLabel("")
        self.time_lbl.setObjectName("miniArtist")
        ctr.addWidget(self.time_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        col.addLayout(ctr)
        lay.addLayout(col, 1)

        self.lyrics_btn.clicked.connect(lambda: self._toggle_lyrics())
        self.expand_btn.clicked.connect(self.expandRequested)
        self.close_btn.clicked.connect(self.expandRequested)
        self.shuffle_btn.clicked.connect(lambda: self.player.set_shuffle(not self.player.shuffle))
        self.repeat_btn.clicked.connect(self.player.cycle_repeat)
        self.prev_btn.clicked.connect(self.player.prev)
        self.next_btn.clicked.connect(lambda: self.player.next())
        self.play_btn.clicked.connect(self.win.toggle_play)
        self.player.positionChanged.connect(self._on_position)
        self.player.modesChanged.connect(self.sync_modes)
        self.sync_modes()

    # ------------------------------------------------------------ estado
    def card(self) -> QRectF:
        return QRectF(self.rect()).adjusted(M, M, -M, -M)

    def set_track(self, t):
        if t is None:
            return
        self.title.setText(t.title)
        self.artist.setText(t.artist_display)
        self.cover.setPixmap(self.covers.get(t.cover, 92, 12, seed=t.album_display))
        img = load_image_small(t.cover, 12)
        self.bg = img.scaled(48, 48, Qt.AspectRatioMode.IgnoreAspectRatio,
                             Qt.TransformationMode.SmoothTransformation) if img else None
        self.update()

    def set_lyrics_mode(self, on: bool):
        """Muestra u oculta la línea de la letra; la ventana crece hacia arriba."""
        self.lyrics_mode = on
        self.lyric.setVisible(on)
        set_active(self.lyrics_btn, on)
        self.lyrics_btn.setToolTip("Ocultar la letra" if on else "Mostrar la letra")
        old_h = self.height()
        self.setFixedSize(CARD_W + 2 * M, CARD_H + (LYRIC_H if on else 0) + 2 * M)
        if self.isVisible():
            self.move(self.x(), self.y() + old_h - self.height())
        self.update()

    def _toggle_lyrics(self):
        self.set_lyrics_mode(not self.lyrics_mode)
        self.lyricsModeChanged.emit(self.lyrics_mode)

    def set_lyric_line(self, text: str):
        self.lyric.setText(text)

    def set_playing(self, playing: bool):
        self.play_btn.setText(G.PAUSE if playing else G.PLAY)
        self.play_btn.setToolTip("Pausar" if playing else "Reproducir")

    def sync_modes(self):
        set_active(self.shuffle_btn, self.player.shuffle)
        set_active(self.repeat_btn, self.player.repeat != REPEAT_OFF)
        self.repeat_btn.setText(G.REPEAT_ONE if self.player.repeat == REPEAT_ONE else G.REPEAT_ALL)

    def _on_position(self, ms):
        if self.isVisible():
            dur = self.player.mp.duration()
            self.time_lbl.setText(f"{fmt_time(ms / 1000)} / {fmt_time(dur / 1000)}" if dur else "")
            self.update()

    def place(self, pos: QPoint | None):
        screen = QGuiApplication.screenAt(pos) if pos is not None else None
        if pos is not None and screen is not None:
            self.move(pos)
        else:
            geo = QGuiApplication.primaryScreen().availableGeometry()
            self.move(geo.right() - self.width() + M - 12, geo.bottom() - self.height() + M - 12)

    # ------------------------------------------------------------ pintura
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        card = self.card()
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(M, 0, -1):  # sombra suave
            p.setBrush(QColor(0, 0, 0, 7))
            p.drawRoundedRect(card.adjusted(-i, -i + 5, i, i + 5), RADIUS + i, RADIUS + i)

        path = QPainterPath()
        path.addRoundedRect(card, RADIUS, RADIUS)
        p.save()
        p.setClipPath(path)
        accent = QColor(self.state.accent)
        if self.bg is not None:
            p.drawImage(card, self.bg)
            p.fillRect(card, QColor(8, 8, 12, 140))
        else:
            p.fillRect(card, QColor(22, 22, 30))
        g = QLinearGradient(card.topLeft(), card.bottomRight())
        a1 = QColor(accent); a1.setAlpha(110)
        a2 = QColor(accent); a2.setAlpha(0)
        g.setColorAt(0, a1)
        g.setColorAt(0.65, a2)
        p.fillRect(card, g)
        shade = QLinearGradient(0, card.top(), 0, card.bottom())
        shade.setColorAt(0, QColor(0, 0, 0, 0))
        shade.setColorAt(1, QColor(0, 0, 0, 90))
        p.fillRect(card, shade)

        # barra de progreso
        bar = self.progress_rect()
        p.setBrush(QColor(255, 255, 255, 45))
        p.drawRoundedRect(bar, 1.5, 1.5)
        dur = self.player.mp.duration()
        if dur > 0:
            done = QRectF(bar)
            done.setWidth(bar.width() * min(1.0, self.player.mp.position() / dur))
            p.setBrush(QColor("#ffffff"))
            p.drawRoundedRect(done, 1.5, 1.5)
        p.restore()

        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 28), 1))
        p.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), RADIUS, RADIUS)

    def progress_rect(self) -> QRectF:
        card = self.card()
        return QRectF(card.left() + 18, card.bottom() - 11, card.width() - 36, 3)

    # ------------------------------------------------------------ ratón
    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        bar = self.progress_rect().adjusted(0, -7, 0, 7)
        pos = e.position()
        dur = self.player.mp.duration()
        if bar.contains(pos) and dur > 0:
            frac = (pos.x() - bar.left()) / bar.width()
            self.player.seek(max(0.0, min(1.0, frac)) * dur)
        elif self.windowHandle():
            self.windowHandle().startSystemMove()

    def mouseDoubleClickEvent(self, e):
        if not self.progress_rect().adjusted(0, -7, 0, 7).contains(e.position()):
            self.expandRequested.emit()

    def wheelEvent(self, e):
        self.win.change_volume(5 if e.angleDelta().y() > 0 else -5)
