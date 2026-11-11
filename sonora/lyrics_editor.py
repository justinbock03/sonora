"""Editor de letras: pegar el texto, sincronizarlo línea por línea, guardarlo y (opcional) publicarlo."""
import difflib

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QLinearGradient, QPainter, QPainterPath, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QGridLayout, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit,
                               QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from .lyrics import Lyrics, parse_lrc
from .lyrics_view import lyrics_colors
from .theme import G
from .widgets import ElidedLabel, fmt_time, icon_button

NUDGE_MS = 100


def align_times(old_lines: list, old_times: list, new_lines: list) -> list:
    """Conserva las marcas de tiempo al corregir el texto.

    Las líneas iguales mantienen su tiempo; las corregidas (p. ej. «Auítate» → «Quítate»)
    heredan el de la línea que reemplazan; sólo las líneas realmente nuevas quedan sin marcar.
    """
    times = [None] * len(new_lines)
    if not old_lines:
        return times
    sm = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            times[j1:j2] = old_times[i1:i2]
        elif tag == "replace" and i2 - i1 == j2 - j1:
            times[j1:j2] = old_times[i1:i2]   # mismas líneas, con el texto corregido
        elif tag == "replace":
            # Distinta cantidad (se corrigió y además se agregó/quitó algo): emparejar por parecido.
            prev = i1 - 1
            for j in range(j1, j2):
                best, score = None, 0.0
                for i in range(prev + 1, i2):
                    r = difflib.SequenceMatcher(None, old_lines[i].lower(), new_lines[j].lower()).ratio()
                    if r > score:
                        best, score = i, r
                if best is not None and score >= 0.6:
                    times[j] = old_times[best]
                    prev = best
    return times


def fmt_ms(ms) -> str:
    if ms is None:
        return "--:--.--"
    cs = round(ms / 10)
    m, rem = divmod(cs, 6000)
    s, c = divmod(rem, 100)
    return f"{m:02d}:{s:02d}.{c:02d}"


def _button(text: str, name: str = "pill", tip: str = "") -> QPushButton:
    b = QPushButton(text)
    b.setObjectName(name)
    b.setToolTip(tip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return b


def _hint(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("editorHint")
    lbl.setWordWrap(True)
    return lbl


class LyricsEditor(QWidget):
    closeRequested = Signal()
    saveRequested = Signal(object, object, dict, bool)   # canción, Lyrics, datos para LRCLIB, publicar

    def __init__(self, state, covers, player):
        super().__init__()
        self.state, self.covers, self.player = state, covers, player
        self.track = None
        self.lines: list[str] = []
        self.times: list = []
        self.pointer = 0
        self.mode = "synced"     # synced | plain | instrumental
        self.active_row = -1
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 22, 22, 18)
        lay.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(14)
        self.cover = QLabel()
        self.cover.setFixedSize(56, 56)
        head.addWidget(self.cover)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.title = ElidedLabel("Editar letra", "lyricsTitle")
        self.sub = ElidedLabel("", "lyricsArtist")
        col.addWidget(self.title)
        col.addWidget(self.sub)
        head.addLayout(col, 1)
        self.close_btn = icon_button(G.CLOSE, "Cerrar el editor", "lyricsBtn", 34)
        head.addWidget(self.close_btn, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(head)

        steps = QHBoxLayout()
        steps.setSpacing(6)
        self.step_group = QButtonGroup(self)
        self.step_btns = []
        for i, name in enumerate(("1  Texto", "2  Sincronizar", "3  Guardar")):
            b = _button(name, "stepBtn")
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=i: self.go(k))
            self.step_group.addButton(b)
            self.step_btns.append(b)
            steps.addWidget(b)
        steps.addStretch(1)
        lay.addLayout(steps)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_text_page())
        self.pages.addWidget(self._build_sync_page())
        self.pages.addWidget(self._build_save_page())
        lay.addWidget(self.pages, 1)

        self.close_btn.clicked.connect(self.closeRequested)
        # Atajos del paso «Sincronizar». Son de ventana (no dependen de qué tenga el foco) y
        # sólo actúan en ese paso; los campos de texto se quedan con sus teclas como siempre.
        for key, action in ((Qt.Key.Key_Backspace, self.undo),
                            (Qt.Key.Key_Left, lambda: self.nudge(-NUDGE_MS)),
                            (Qt.Key.Key_Right, lambda: self.nudge(NUDGE_MS)),
                            (Qt.Key.Key_Up, lambda: self.move_selection(-1)),
                            (Qt.Key.Key_Down, lambda: self.move_selection(1)),
                            (Qt.Key.Key_F2, self.edit_line)):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.setAutoRepeat(key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down))
            sc.activated.connect(lambda a=action: self.on_sync_page() and a())

    # ------------------------------------------------------------ páginas
    def _build_text_page(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        v.addWidget(_hint("Pega o escribe la letra, un verso por línea. Las líneas vacías separan estrofas. "
                          "Si pegas un archivo .lrc con tiempos, se conservan."))
        self.text = QPlainTextEdit()
        self.text.setObjectName("lyricsEdit")
        self.text.setPlaceholderText("Escribe o pega aquí la letra…")
        v.addWidget(self.text, 1)
        row = QHBoxLayout()
        self.instr_btn = _button("Es instrumental", tip="La canción no tiene letra cantada")
        self.plain_btn = _button("Guardar sin sincronizar", tip="Guardar sólo el texto, sin tiempos")
        self.to_sync = _button("Sincronizar  →", "accentPill")
        row.addWidget(self.instr_btn)
        row.addStretch(1)
        row.addWidget(self.plain_btn)
        row.addWidget(self.to_sync)
        v.addLayout(row)
        self.instr_btn.clicked.connect(lambda: self._finish_mode("instrumental"))
        self.plain_btn.clicked.connect(lambda: self._finish_mode("plain"))
        self.to_sync.clicked.connect(lambda: self.go(1))
        return page

    def _build_sync_page(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        v.addWidget(_hint("Reproduce la canción y pulsa ESPACIO justo cuando empieza cada línea.   "
                          "← / →  ajustan ±0,1 s la línea seleccionada (tras marcar, es la última marcada)  ·  "
                          "↑ / ↓  eligen otra línea  ·  F2 corrige el texto de la línea  ·  "
                          "Retroceso deshace  ·  doble clic la escucha desde ahí."))
        self.list = QListWidget()
        self.list.setObjectName("syncList")
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.itemDoubleClicked.connect(self._preview)
        v.addWidget(self.list, 1)

        row1 = QHBoxLayout()
        row1.setSpacing(6)
        self.mark_btn = _button("Marcar  (Espacio)", "accentPill")
        self.undo_btn = _button("Deshacer  (⌫)", tip="Quita la última marca y retrocede un poco")
        self.minus_btn = _button("−0,1 s  (←)", tip="Adelanta la línea seleccionada")
        self.plus_btn = _button("+0,1 s  (→)", tip="Retrasa la línea seleccionada")
        for b in (self.mark_btn, self.undo_btn, self.minus_btn, self.plus_btn):
            row1.addWidget(b)
        row1.addStretch(1)
        self.sync_status = QLabel("")
        self.sync_status.setObjectName("editorHint")
        row1.addWidget(self.sync_status)
        v.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(6)
        self.edit_line_btn = _button("Corregir línea  (F2)", tip="Cambia el texto de la línea seleccionada sin perder su tiempo")
        self.here_btn = _button("Marcar desde aquí", tip="Vuelve a marcar a partir de la línea seleccionada")
        self.restart_btn = _button("Empezar de nuevo", tip="Borra todas las marcas y reproduce desde el inicio")
        for b in (self.edit_line_btn, self.here_btn, self.restart_btn):
            row2.addWidget(b)
        row2.addStretch(1)
        self.to_save = _button("Continuar  →", "accentPill")
        row2.addWidget(self.to_save)
        v.addLayout(row2)

        self.restart_btn.clicked.connect(self.restart)
        self.mark_btn.clicked.connect(self.mark)
        self.undo_btn.clicked.connect(self.undo)
        self.minus_btn.clicked.connect(lambda: self.nudge(-NUDGE_MS))
        self.plus_btn.clicked.connect(lambda: self.nudge(NUDGE_MS))
        self.here_btn.clicked.connect(self.mark_from_here)
        self.edit_line_btn.clicked.connect(self.edit_line)
        self.to_save.clicked.connect(lambda: self._finish_mode("synced"))
        return page

    def _build_save_page(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        self.summary = QLabel("")
        self.summary.setObjectName("panelHeading")
        v.addWidget(self.summary)
        v.addWidget(_hint("La letra se guarda en tu PC como archivo .lrc junto a la canción "
                          "(así también la ven otros reproductores)."))
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        self.f_title, self.f_artist, self.f_album = QLineEdit(), QLineEdit(), QLineEdit()
        for r, (label, field) in enumerate((("Título", self.f_title), ("Artista", self.f_artist),
                                            ("Álbum", self.f_album))):
            field.setObjectName("editorField")
            lbl = QLabel(label)
            lbl.setObjectName("editorHint")
            grid.addWidget(lbl, r, 0)
            grid.addWidget(field, r, 1)
        self.f_duration = QLabel("")
        lbl = QLabel("Duración")
        lbl.setObjectName("editorHint")
        grid.addWidget(lbl, 3, 0)
        grid.addWidget(self.f_duration, 3, 1)
        v.addLayout(grid)
        self.publish_chk = QCheckBox("Publicar también en LRCLIB para que cualquiera pueda verla")
        self.publish_chk.setCursor(Qt.CursorShape.PointingHandCursor)
        v.addWidget(self.publish_chk)
        v.addWidget(_hint("Si publicas, se envían a LRCLIB el título, el artista, el álbum y la duración de "
                          "arriba junto con la letra. LRCLIB usa esos datos para encontrarla, así que deben "
                          "coincidir con la canción. Lo publicado es público y no se puede borrar desde Sonora; "
                          "revisa que la letra y los tiempos estén bien."))
        v.addStretch(1)
        row = QHBoxLayout()
        self.status = QLabel("")
        self.status.setObjectName("editorStatus")
        self.status.setWordWrap(True)
        row.addWidget(self.status, 1)
        self.cancel_pub = _button("Cancelar publicación")
        self.cancel_pub.hide()
        self.save_btn = _button("Guardar", "accentPill")
        row.addWidget(self.cancel_pub)
        row.addWidget(self.save_btn)
        v.addLayout(row)
        self.save_btn.clicked.connect(self._save)
        return page

    # ------------------------------------------------------------ abrir / navegar
    def open(self, track, lyrics):
        self.track = track
        self.cover.setPixmap(self.covers.get(track.cover, 56, 8, seed=track.album_display))
        self.title.setText("Editar letra" if lyrics else "Agregar letra")
        self.sub.setText(f"{track.title} — {track.artist_display}")
        self.lines, self.times, self.pointer = [], [], 0
        if lyrics is not None and lyrics.synced:
            self.lines = [t for _, t in lyrics.lines if t.strip()]
            self.times = [ms for ms, t in lyrics.lines if t.strip()]
            self.pointer = len(self.lines)
            self.text.setPlainText("\n".join(t for _, t in lyrics.lines))
        elif lyrics is not None and not lyrics.instrumental:
            self.text.setPlainText(lyrics.plain)
        else:
            self.text.clear()
        self.f_title.setText(track.title)
        self.f_artist.setText(track.artist)
        self.f_album.setText(track.album)
        self.f_duration.setText(f"{fmt_time(track.duration)}  ({round(track.duration)} s)")
        self.publish_chk.setChecked(False)
        self.set_status("")
        self.set_publishing(False)
        self.mode = "synced"
        self.go(0)

    def go(self, step: int):
        if step >= 1 and self.mode != "instrumental" and not self.text.toPlainText().strip():
            self.step_btns[self.pages.currentIndex()].setChecked(True)
            self.text.setFocus()
            return
        if step == 1:
            self._prepare_sync()
            self.setFocus()
        if step == 2:
            self._update_summary()
        self.pages.setCurrentIndex(step)
        self.step_btns[step].setChecked(True)

    def on_sync_page(self) -> bool:
        return self.isVisible() and self.pages.currentIndex() == 1

    def _finish_mode(self, mode: str):
        self.mode = mode
        self.go(2)

    # ------------------------------------------------------------ sincronizar
    def _prepare_sync(self):
        raw = self.text.toPlainText()
        parsed = parse_lrc(raw)
        if parsed:  # se pegó un .lrc: conservar sus tiempos y dejar sólo el texto en el paso 1
            lines = [t for _, t in parsed if t.strip()]
            times = [ms for ms, t in parsed if t.strip()]
            self.text.setPlainText("\n".join(t for _, t in parsed))
        else:
            lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
            times = align_times(self.lines, self.times, lines)
        self.lines, self.times = lines, list(times)
        self.pointer = next((i for i, t in enumerate(self.times) if t is None), len(self.lines))
        self.mode = "synced"
        self.list.clear()
        for _ in self.lines:
            self.list.addItem(QListWidgetItem(""))
        self.active_row = -1
        self._update_rows(range(len(self.lines)))
        last = self._last_marked()
        if last is not None:
            self.list.setCurrentRow(last)

    def _last_marked(self):
        marked = [i for i in range(min(self.pointer, len(self.times))) if self.times[i] is not None]
        return marked[-1] if marked else None

    def move_selection(self, step: int):
        if not self.lines:
            return
        r = self.list.currentRow()
        r = 0 if r < 0 else max(0, min(len(self.lines) - 1, r + step))
        self.list.setCurrentRow(r)
        self.list.scrollToItem(self.list.item(r))

    def edit_line(self):
        """Corrige el texto de la línea seleccionada sin perder su tiempo (y lo refleja en el paso 1)."""
        if not self.lines:
            return
        r = self.list.currentRow()
        if not 0 <= r < len(self.lines):
            last = self._last_marked()
            r = last if last is not None else 0
        new, ok = QInputDialog.getText(self, "Corregir línea", f"Línea {r + 1}:", QLineEdit.EchoMode.Normal,
                                       self.lines[r])
        new = new.strip()
        if not ok or not new or new == self.lines[r]:
            return
        raw = self.text.toPlainText().split("\n")
        k = -1
        for idx, ln in enumerate(raw):
            if ln.strip():
                k += 1
                if k == r:
                    raw[idx] = new
                    break
        self.lines[r] = new
        self.text.setPlainText("\n".join(raw))
        self._update_rows((r,))
        self.list.setCurrentRow(r)

    def _update_rows(self, rows):
        accent = self.state.accent.lighter(140)
        for i in rows:
            if not 0 <= i < len(self.lines):
                continue
            item = self.list.item(i)
            marker = "▸" if i == self.pointer else " "
            item.setText(f"{marker}  {fmt_ms(self.times[i])}     {self.lines[i]}")
            if i == self.active_row:
                item.setForeground(accent)
            elif self.times[i] is None:
                item.setForeground(QColor(255, 255, 255, 120))
            else:
                item.setForeground(QColor(255, 255, 255, 230))
            f = item.font()
            f.setBold(i == self.pointer or i == self.active_row)
            item.setFont(f)
        done = sum(t is not None for t in self.times)
        self.sync_status.setText(f"{done} de {len(self.lines)} líneas marcadas")
        if 0 <= self.pointer < len(self.lines):
            self.list.scrollToItem(self.list.item(self.pointer), QAbstractItemView.ScrollHint.PositionAtCenter)

    def mark(self):
        if self.pointer >= len(self.lines):
            return
        if self.track is None or self.state.current_path != self.track.path:
            self.sync_status.setText("⚠ Está sonando otra canción: vuelve a la que estás sincronizando")
            return
        ms = int(self.player.mp.position())
        prev = self.times[self.pointer - 1] if self.pointer > 0 else None
        if prev is not None and ms < prev:   # mantener el orden aunque se marque muy seguido
            ms = prev
        self.times[self.pointer] = ms
        old = self.pointer
        self.pointer = next((i for i in range(old + 1, len(self.lines)) if self.times[i] is None), len(self.lines))
        self._update_rows((old, self.pointer))
        self.list.setCurrentRow(old)   # ←/→ afinan la línea recién marcada

    def undo(self):
        marked = [i for i in range(self.pointer) if self.times[i] is not None]
        if not marked:
            return
        i = marked[-1]
        old = self.pointer
        self.times[i] = None
        self.pointer = i
        back = self.times[i - 1] if i > 0 and self.times[i - 1] is not None else 0
        self.player.seek(max(0, back - 1000))
        self._update_rows((i, old))
        last = self._last_marked()
        self.list.setCurrentRow(last if last is not None else i)

    def nudge(self, delta: int):
        r = self.list.currentRow()
        if 0 <= r < len(self.times) and self.times[r] is not None:
            self.times[r] = max(0, self.times[r] + delta)
            self.player.seek(max(0, self.times[r] - 800))
            self._update_rows((r,))

    def mark_from_here(self):
        r = self.list.currentRow()
        if not 0 <= r < len(self.lines):
            return
        for i in range(r, len(self.times)):
            self.times[i] = None
        old = self.pointer
        self.pointer = r
        back = self.times[r - 1] if r > 0 and self.times[r - 1] is not None else 0
        self.player.seek(max(0, back - 1500))
        self._update_rows(range(min(r, old), len(self.lines)))

    def restart(self):
        self.times = [None] * len(self.lines)
        self.pointer = 0
        self.player.seek(0)
        if not self.player.is_playing():
            self.player.mp.play()
        self._update_rows(range(len(self.lines)))

    def _preview(self, item):
        r = self.list.row(item)
        t = self.times[r]
        if t is None:
            t = next((self.times[i] for i in range(r - 1, -1, -1) if self.times[i] is not None), 0)
        self.player.seek(max(0, t - 300))
        if not self.player.is_playing():
            self.player.mp.play()

    def on_position(self, ms: int):
        """Resalta la línea que suena según las marcas, para comprobar la sincronización."""
        if not self.on_sync_page():
            return
        active = -1
        for i, t in enumerate(self.times):
            if t is not None and t <= ms:
                active = i
        if active != self.active_row:
            old, self.active_row = self.active_row, active
            self._update_rows((old, active))

    # ------------------------------------------------------------ guardar
    def _update_summary(self):
        if self.mode == "instrumental":
            self.summary.setText("Marcada como instrumental (sin letra cantada)")
        elif self.mode == "plain":
            n = len([ln for ln in self.text.toPlainText().splitlines() if ln.strip()])
            self.summary.setText(f"Letra sin sincronizar · {n} líneas (podrás sincronizarla después)")
        else:
            missing = sum(t is None for t in self.times)
            self.summary.setText(f"Letra sincronizada · {len(self.lines)} líneas" if not missing else
                                 f"Faltan {missing} líneas por marcar: vuelve al paso 2")

    def build_lyrics(self):
        if self.mode == "instrumental":
            return Lyrics(instrumental=True), "", ""
        raw = self.text.toPlainText()
        parsed = parse_lrc(raw)
        plain = "\n".join(t for _, t in parsed) if parsed else raw.strip()
        if self.mode == "plain":
            return Lyrics([], plain), plain, ""
        if any(t is None for t in self.times) or not self.lines:
            return None, "", ""
        lines = list(zip(self.times, self.lines))
        from .lyrics import format_lrc
        return Lyrics(lines, plain), plain, format_lrc(lines)

    def _save(self):
        lyr, _plain, _synced = self.build_lyrics()
        if lyr is None:
            self.set_status("Faltan líneas por marcar. Vuelve al paso 2 para terminar la sincronización.", False)
            return
        meta = {"trackName": self.f_title.text().strip(), "artistName": self.f_artist.text().strip(),
                "albumName": self.f_album.text().strip(), "duration": round(self.track.duration)}
        publish = self.publish_chk.isChecked()
        if publish and not all((meta["trackName"], meta["artistName"], meta["albumName"])):
            self.set_status("Para publicar en LRCLIB hacen falta título, artista y álbum.", False)
            return
        self.saveRequested.emit(self.track, lyr, meta, publish)

    def set_status(self, text: str, ok: bool | None = None):
        self.status.setText(text)
        color = {True: "#8ef0a8", False: "#ff9b9b"}.get(ok, "rgba(255,255,255,0.8)")
        self.status.setStyleSheet(f"color: {color};")

    def set_publishing(self, busy: bool):
        self.cancel_pub.setVisible(busy)
        self.save_btn.setEnabled(not busy)
        for b in self.step_btns:
            b.setEnabled(not busy)

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
