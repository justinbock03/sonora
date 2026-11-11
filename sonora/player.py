"""Motor de reproducción: cola, aleatorio y repetición sobre QMediaPlayer (FFmpeg)."""
import random

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

REPEAT_OFF, REPEAT_ALL, REPEAT_ONE = 0, 1, 2


class Player(QObject):
    trackChanged = Signal(object)
    playingChanged = Signal(bool)
    positionChanged = Signal("qlonglong")
    durationChanged = Signal("qlonglong")
    queueChanged = Signal()
    modesChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.audio = QAudioOutput(self)
        self.mp = QMediaPlayer(self)
        self.mp.setAudioOutput(self.audio)
        self.queue: list = []   # pistas en el orden original
        self.order: list[int] = []  # índices de `queue` en orden de reproducción
        self.pos = -1
        self.shuffle = False
        self.repeat = REPEAT_OFF
        self.volume = 0.7
        self.muted = False
        self.pending_seek = None
        self._errors = 0
        self.mp.positionChanged.connect(self.positionChanged)
        self.mp.durationChanged.connect(self.durationChanged)
        self.mp.playbackStateChanged.connect(
            lambda s: self.playingChanged.emit(s == QMediaPlayer.PlaybackState.PlayingState))
        self.mp.mediaStatusChanged.connect(self._on_status)
        self.mp.errorOccurred.connect(self._on_error)
        self.set_volume(self.volume)

    # ------------------------------------------------------------ estado
    @property
    def current(self):
        if 0 <= self.pos < len(self.order):
            return self.queue[self.order[self.pos]]
        return None

    def is_playing(self) -> bool:
        return self.mp.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def ordered(self) -> list:
        return [self.queue[i] for i in self.order]

    def upcoming(self, n: int = 6) -> list:
        return [self.queue[i] for i in self.order[self.pos + 1:self.pos + 1 + n]]

    # ------------------------------------------------------------ cola
    def play_list(self, tracks, start: int = 0, play: bool = True):
        if not tracks:
            return
        self.queue = list(tracks)
        self._build_order(max(0, min(start, len(self.queue) - 1)))
        self._errors = 0
        self._load(play)
        self.queueChanged.emit()

    def _build_order(self, current: int):
        n = len(self.queue)
        if self.shuffle:
            rest = [i for i in range(n) if i != current]
            random.shuffle(rest)
            self.order = [current] + rest
            self.pos = 0
        else:
            self.order = list(range(n))
            self.pos = current

    def play_next(self, tracks):
        if self.current is None:
            return self.play_list(tracks)
        for k, t in enumerate(tracks):
            self.queue.append(t)
            self.order.insert(self.pos + 1 + k, len(self.queue) - 1)
        self.queueChanged.emit()

    def enqueue(self, tracks):
        if self.current is None:
            return self.play_list(tracks)
        for t in tracks:
            self.queue.append(t)
            self.order.append(len(self.queue) - 1)
        self.queueChanged.emit()

    def jump(self, order_index: int):
        if 0 <= order_index < len(self.order):
            self.pos = order_index
            self._load(True)
            self.queueChanged.emit()

    def _load(self, play: bool):
        t = self.current
        if t is None:
            return
        self.mp.setSource(QUrl.fromLocalFile(t.path))
        if play:
            self.mp.play()
        self.trackChanged.emit(t)

    # ------------------------------------------------------------ transporte
    def toggle(self):
        if self.current is None:
            return False
        if self.is_playing():
            self.mp.pause()
        else:
            self.mp.play()
        return True

    def next(self, auto: bool = False):
        if not self.order:
            return
        if auto and self.repeat == REPEAT_ONE:
            self.mp.setPosition(0)
            self.mp.play()
            return
        if self.pos + 1 < len(self.order):
            self.pos += 1
        else:
            if self.shuffle and self.repeat == REPEAT_ALL:
                random.shuffle(self.order)
            self.pos = 0
            if auto and self.repeat == REPEAT_OFF:
                self._load(False)
                self.queueChanged.emit()
                return
        self._load(True)
        self.queueChanged.emit()

    def prev(self):
        if self.mp.position() > 3000 or self.pos <= 0:
            self.mp.setPosition(0)
            return
        self.pos -= 1
        self._load(True)
        self.queueChanged.emit()

    def seek(self, ms: int):
        self.mp.setPosition(int(ms))

    def set_shuffle(self, on: bool):
        self.shuffle = on
        if self.order:
            self._build_order(self.order[self.pos])
            self.queueChanged.emit()
        self.modesChanged.emit()

    def cycle_repeat(self):
        self.repeat = (self.repeat + 1) % 3
        self.modesChanged.emit()

    def set_volume(self, v: float):
        self.volume = max(0.0, min(1.0, v))
        self.audio.setVolume(self.volume ** 2)  # curva aproximadamente perceptual

    def set_muted(self, m: bool):
        self.muted = m
        self.audio.setMuted(m)

    # ------------------------------------------------------------ eventos
    def _on_status(self, status):
        S = QMediaPlayer.MediaStatus
        if status == S.EndOfMedia:
            self.next(auto=True)
        elif status in (S.LoadedMedia, S.BufferedMedia):
            self._errors = 0
            if self.pending_seek:
                self.mp.setPosition(self.pending_seek)
                self.pending_seek = None

    def _on_error(self, *_):
        self._errors += 1
        if self._errors < len(self.order):
            QTimer.singleShot(0, lambda: self.next())
        else:
            self.mp.stop()
