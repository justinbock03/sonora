"""Letras de canciones.

Orden de búsqueda:
  1. Archivo .lrc junto a la canción (mismo nombre).
  2. Letra guardada por el usuario en Sonora (si no se pudo escribir junto a la canción).
  3. Letra incrustada en las etiquetas del archivo (ID3 SYLT/USLT, Vorbis, MP4, WMA, APE).
  4. LRCLIB (https://lrclib.net), base de datos libre y gratuita; muchas letras vienen
     sincronizadas con marcas de tiempo. El resultado (o su ausencia) se guarda en caché.

También permite guardar letras escritas/sincronizadas por el usuario y publicarlas en LRCLIB.
"""
import hashlib
import json
import random
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path

import mutagen
from PySide6.QtCore import QObject, Signal

from . import lyrics_netease as netease
from .library import APP_DIR
from .lyrics_netease import NetEaseError

LYRICS_DIR = APP_DIR / "lyrics"
API = "https://lrclib.net/api"
USER_AGENT = "Sonora/2.0 (reproductor de musica personal)"
RETRY_MISSING = 7 * 24 * 3600   # volver a buscar en línea una letra no encontrada tras 7 días

_TIME_TAG = re.compile(r"\[(\d{1,3}):(\d{1,2}(?:[.:]\d{1,3})?)\]")
_WORD_TAG = re.compile(r"<\d{1,3}:\d{1,2}(?:[.:]\d{1,3})?>")
_OFFSET = re.compile(r"\[offset:\s*([+-]?\d+)\s*\]", re.IGNORECASE)
_FEAT = re.compile(r"\s*[\(\[](?:feat|ft|with|con)\.?\s[^\)\]]*[\)\]]", re.IGNORECASE)
_REMASTER = re.compile(r"\s*(?:-\s*(?:\d{4}\s*)?remaster(?:ed)?.*$|[\(\[][^\)\]]*remaster[^\)\]]*[\)\]])",
                       re.IGNORECASE)


@dataclass
class Lyrics:
    lines: list = field(default_factory=list)   # [(ms, texto)] si está sincronizada
    plain: str = ""
    source: str = ""
    instrumental: bool = False

    @property
    def synced(self) -> bool:
        return bool(self.lines)

    def index_at(self, ms: int) -> int:
        """Índice de la línea que suena en `ms` (-1 antes de la primera)."""
        return bisect_right([t for t, _ in self.lines], ms) - 1

    def to_dict(self) -> dict:
        return {"lines": self.lines, "plain": self.plain, "source": self.source,
                "instrumental": self.instrumental}

    @classmethod
    def from_dict(cls, d: dict) -> "Lyrics":
        return cls([tuple(x) for x in d.get("lines", [])], d.get("plain", ""),
                   d.get("source", ""), d.get("instrumental", False))


class LyricsNetworkError(Exception):
    pass


MIN_LINE_MS, MAX_LINE_MS = 3000, 12000   # cuánto puede durar cantada una línea
MIN_BREAK_MS = 5000                      # con menos, suele ser una nota alargada y no un instrumental


def with_music_breaks(lyr: Lyrics | None, duration_s: float = 0.0) -> Lyrics | None:
    """Copia de la letra, sólo para mostrar, con ♪ en los tramos largos sin voz.

    El formato LRC sólo indica cuándo empieza cada línea, así que su final se estima con el
    ritmo de la propia canción (milisegundos por letra, mediana entre líneas consecutivas).
    """
    if lyr is None or not lyr.synced:
        return lyr
    lines = lyr.lines
    paces = sorted((lines[i + 1][0] - lines[i][0]) / len(lines[i][1].strip())
                   for i in range(len(lines) - 1) if len(lines[i][1].strip()) >= 8)
    pace = max(70.0, min(220.0, paces[len(paces) // 2])) if paces else 110.0
    end = int(duration_s * 1000)
    out = []
    for i, (ms, text) in enumerate(lines):
        out.append((ms, text))
        following = lines[i + 1] if i + 1 < len(lines) else (end, "x")
        if not text.strip() or not following[1].strip():
            continue  # la propia letra ya marca aquí una pausa
        finish = ms + int(max(MIN_LINE_MS, min(MAX_LINE_MS, len(text.strip()) * pace * 1.25)))
        if following[0] - finish >= MIN_BREAK_MS:
            out.append((finish, ""))
    return Lyrics(out, lyr.plain, lyr.source, lyr.instrumental)


# ---------------------------------------------------------------- análisis

def parse_lrc(text: str) -> list:
    m = _OFFSET.search(text)
    offset = int(m.group(1)) if m else 0
    out = []
    for raw in text.splitlines():
        tags = list(_TIME_TAG.finditer(raw))
        if not tags or tags[0].start() != 0:
            continue
        content = _WORD_TAG.sub("", _TIME_TAG.sub("", raw)).strip()
        for t in tags:
            secs = int(t.group(1)) * 60 + float(t.group(2).replace(":", "."))
            out.append((max(0, int(secs * 1000) - offset), content))
    out.sort(key=lambda x: x[0])
    return out


def from_text(text: str, source: str) -> Lyrics | None:
    text = (text or "").replace("\r\n", "\n").strip()
    if not text:
        return None
    lines = parse_lrc(text)
    if lines:
        plain = "\n".join(t for _, t in lines)
        return Lyrics(lines, plain, source)
    return Lyrics([], text, source)


def from_sidecar(path: str) -> Lyrics | None:
    lrc = Path(path).with_suffix(".lrc")
    if not lrc.exists():
        return None
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return from_text(lrc.read_text(encoding=enc), "Archivo .lrc")
        except (UnicodeDecodeError, OSError):
            continue
    return None


def from_tags(path: str) -> Lyrics | None:
    try:
        audio = mutagen.File(path)
    except Exception:
        return None
    tags = getattr(audio, "tags", None)
    if not tags:
        return None
    source = "Etiquetas del archivo"
    try:
        if hasattr(tags, "getall"):  # ID3 (MP3, WAV, AIFF)
            for sylt in tags.getall("SYLT"):
                if sylt.format == 2 and sylt.text:  # marcas en milisegundos
                    lines = sorted((int(ms), txt.strip()) for txt, ms in sylt.text)
                    return Lyrics(lines, "\n".join(t for _, t in lines), source)
            for uslt in tags.getall("USLT"):
                lyr = from_text(uslt.text, source)
                if lyr:
                    return lyr
            return None
        for key in ("lyrics", "unsyncedlyrics", "LYRICS", "\xa9lyr", "WM/Lyrics", "Lyrics"):
            v = tags.get(key)
            if not v:
                continue
            if isinstance(v, list):
                v = v[0]
            v = getattr(v, "value", v)
            lyr = from_text(str(v), source)
            if lyr:
                return lyr
    except Exception:
        return None
    return None


# ---------------------------------------------------------------- LRCLIB

MIN_INTERVAL = 1.4   # s entre consultas: < 45/min, el límite de LRCLIB para clientes no registrados
_rate_lock = threading.Lock()
_last_request = 0.0


def _throttle():
    """Una consulta a la vez y espaciadas, como pide la documentación de LRCLIB."""
    global _last_request
    with _rate_lock:
        wait = _last_request + MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()


def _retry_after(e: urllib.error.HTTPError, attempt: int) -> float:
    """Espera indicada por el servidor (Retry-After, obligatorio respetarla) + hasta 30 % al azar."""
    try:
        base = float(e.headers.get("Retry-After"))
    except (TypeError, ValueError):
        base = 0.8 * (attempt + 1)
    return min(base, 60) * (1 + random.random() * 0.3)


def _request(endpoint: str, params: dict):
    url = f"{API}/{endpoint}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(4):
        _throttle()
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            # 429/5xx: el servidor está ocupado de forma temporal; reintentar con espera.
            if (e.code == 429 or e.code >= 500) and attempt < 3:
                time.sleep(_retry_after(e, attempt))
                continue
            raise LyricsNetworkError(f"El servidor de letras no responde (error {e.code})") from e
        except TimeoutError as e:
            if attempt < 2:
                continue
            raise LyricsNetworkError("El servidor de letras tarda demasiado") from e
        except (urllib.error.URLError, OSError) as e:
            raise LyricsNetworkError("Sin conexión a internet") from e


def _to_lyrics(d: dict) -> Lyrics:
    if d.get("instrumental"):
        return Lyrics(source="LRCLIB", instrumental=True)
    synced = d.get("syncedLyrics") or ""
    lines = parse_lrc(synced) if synced else []
    return Lyrics(lines, d.get("plainLyrics") or "\n".join(t for _, t in lines), "LRCLIB")


def clean_title(title: str) -> str:
    return _REMASTER.sub("", _FEAT.sub("", title)).strip() or title


def fetch_online(track) -> Lyrics | None:
    artist = track.artists[0] if track.artist else ""
    title = clean_title(track.title)
    dur = round(track.duration or 0)
    if artist and dur:
        d = _request("get", {"track_name": track.title, "artist_name": track.artist,
                             "album_name": track.album, "duration": dur})
        if d and (d.get("syncedLyrics") or d.get("plainLyrics") or d.get("instrumental")):
            return _to_lyrics(d)
    attempts = [{"track_name": title, "artist_name": artist}] if artist else []
    attempts.append({"q": f"{artist} {title}".strip()})
    for params in attempts:
        results = _request("search", params) or []
        best = _best_match(results, dur)
        if best:
            return _to_lyrics(best)
    return None


def _best_match(results: list, dur: int):
    usable = [r for r in results if r.get("syncedLyrics") or r.get("plainLyrics") or r.get("instrumental")]
    if dur:
        usable = [r for r in usable if abs((r.get("duration") or 0) - dur) <= 4]
    # Preferir letras sincronizadas y la duración más parecida.
    usable.sort(key=lambda r: (not r.get("syncedLyrics"), abs((r.get("duration") or 0) - dur)))
    return usable[0] if usable else None


# ---------------------------------------------------------------- caché + servicio

def _cache_file(path: str) -> Path:
    return LYRICS_DIR / (hashlib.md5(path.lower().encode("utf-8", "ignore")).hexdigest() + ".json")


def load_lyrics(track, force_online: bool = False) -> Lyrics | None:
    return load_lyrics_ex(track, force_online)[0]


def load_local(track) -> Lyrics | None:
    """Letra ya disponible en el equipo (archivo, etiquetas o caché), sin consultar internet."""
    return load_lyrics_ex(track, local_only=True)[0]


def load_lyrics_ex(track, force_online: bool = False, local_only: bool = False) -> tuple[Lyrics | None, bool]:
    """(letra, se_consultó_internet)."""
    lyr = from_sidecar(track.path) or from_user_store(track.path) or from_tags(track.path)
    if lyr:
        return lyr, False
    cache = _cache_file(track.path)
    only_netease = False
    if cache.exists() and not force_online:
        try:
            d = json.loads(cache.read_text(encoding="utf-8"))
            if d.get("missing"):
                if time.time() - d.get("time", 0) < RETRY_MISSING:
                    # Ya se buscó en LRCLIB hace poco; si NetEase se activó después, probar sólo ahí.
                    if not (SOURCES["netease"] and "netease" not in d.get("tried", ["lrclib"])):
                        return None, False
                    only_netease = True
            else:
                return Lyrics.from_dict(d), False
        except (OSError, ValueError):
            pass
    if local_only:
        return None, False
    tried = ["lrclib"]
    lyr, lrclib_error = None, None
    if not only_netease:
        try:
            lyr = fetch_online(track)
        except LyricsNetworkError as e:
            lrclib_error = e
    if lyr is None and SOURCES["netease"]:
        try:
            lyr = fetch_netease(track)
            tried.append("netease")
        except NetEaseError:
            pass  # NetEase es sólo un respaldo: si falla, cuenta lo que diga LRCLIB
    if lyr is None and lrclib_error is not None:
        raise lrclib_error  # no se guarda en caché: se reintentará
    LYRICS_DIR.mkdir(parents=True, exist_ok=True)
    data = lyr.to_dict() if lyr else {"missing": True, "time": time.time(), "tried": tried}
    cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return lyr, True


# Fuentes opcionales (las activa la ventana principal según la configuración del usuario).
SOURCES = {"netease": False}


def fetch_netease(track) -> Lyrics | None:
    found = netease.fetch(track, clean_title(track.title))
    if found is None:
        return None
    lrc, instrumental = found
    if instrumental:
        return Lyrics(source="NetEase", instrumental=True)
    lines = parse_lrc(lrc)
    return Lyrics(lines, "\n".join(t for _, t in lines), "NetEase")


# Estado de la letra de cada canción (para marcarlas en la lista).
SYNCED, PLAIN, INSTRUMENTAL, NONE, ERROR = "synced", "plain", "instrumental", "none", "error"
STATUS_FILE = LYRICS_DIR / "status.json"
CHECK_PAUSE = 0.6               # segundos entre consultas a LRCLIB al revisar la biblioteca
BACKOFF_MIN, BACKOFF_MAX = 30, 600


def classify(lyr: Lyrics | None) -> str:
    if lyr is None:
        return NONE
    if lyr.instrumental:
        return INSTRUMENTAL
    return SYNCED if lyr.synced else PLAIN


class LyricsService(QObject):
    """Busca letras en segundo plano y avisa con señales (en el hilo de la interfaz).

    Además revisa poco a poco toda la biblioteca para saber qué canciones tienen letra,
    reintentando sola, con esperas crecientes, las que fallaron porque el servidor no respondió.
    """
    ready = Signal(str, object)        # ruta, Lyrics | None (no encontrada)
    failed = Signal(str, str)          # ruta, mensaje
    statusChanged = Signal(str, str)   # ruta, estado
    serverTrouble = Signal(int)        # segundos hasta el próximo intento (0 = ya responde)

    def __init__(self):
        super().__init__()
        self.memory: dict = {}
        self.pending: set = set()
        self.lock = threading.Lock()
        # ruta -> [estado, marca de tiempo]; para ERROR la marca es cuándo reintentar
        self.status: dict[str, list] = {}
        self.tracks: list = []
        self.priority: list = []
        self.backoff = 0
        self._dirty = 0
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._load_status()

    # ------------------------------------------------------------ estado
    def _load_status(self):
        try:
            self.status = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.status = {}

    def save_status(self):
        with self.lock:
            data = json.dumps(self.status, ensure_ascii=False)
            self._dirty = 0
        LYRICS_DIR.mkdir(parents=True, exist_ok=True)
        tmp = STATUS_FILE.with_suffix(".tmp")
        tmp.write_text(data, encoding="utf-8")
        tmp.replace(STATUS_FILE)

    def status_of(self, path: str):
        entry = self.status.get(path)
        return entry[0] if entry else None

    def _set_status(self, path: str, status: str, stamp: float | None = None):
        with self.lock:
            old = self.status.get(path)
            self.status[path] = [status, time.time() if stamp is None else stamp]
            self._dirty += 1
            dirty = self._dirty
        if not old or old[0] != status:
            self.statusChanged.emit(path, status)
        if dirty >= 25:
            self.save_status()

    def sources_changed(self):
        """Se activó otra fuente: volver a revisar las canciones que estaban «sin letra»."""
        with self.lock:
            for path in [p for p, e in self.status.items() if e[0] == NONE]:
                del self.status[path]
                self.memory.pop(path, None)
        self.statusChanged.emit("", "")
        self._wake.set()

    def recheck(self, track):
        """Vuelve a buscar la letra de una canción ignorando la caché."""
        with self.lock:
            self.status.pop(track.path, None)
        self.memory.pop(track.path, None)
        self.statusChanged.emit(track.path, "")
        self.request(track, force=True)

    # ------------------------------------------------------------ revisión en segundo plano
    def set_tracks(self, tracks):
        with self.lock:
            self.tracks = list(tracks)
        self._wake.set()

    def set_priority(self, tracks):
        """Canciones a revisar primero (las próximas de la cola)."""
        with self.lock:
            self.priority = list(tracks)
        self._wake.set()

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._check_loop, daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()
        self.save_status()

    def _is_due(self, path: str, now: float) -> bool:
        entry = self.status.get(path)
        if entry is None:
            return True
        status, stamp = entry
        if status == ERROR:
            return stamp <= now
        if status == NONE:
            return now - stamp >= RETRY_MISSING
        return False

    def _next_due(self):
        now = time.time()
        with self.lock:
            for t in self.priority + self.tracks:
                if t.path not in self.pending and self._is_due(t.path, now):
                    return t
        return None

    def _check_loop(self):
        while not self._stop.is_set():
            t = self._next_due()
            if t is None:
                self._wake.wait(60)
                self._wake.clear()
                continue
            try:
                lyr, used_network = load_lyrics_ex(t)
            except LyricsNetworkError:
                self.backoff = min(max(BACKOFF_MIN, self.backoff * 2), BACKOFF_MAX)
                self._set_status(t.path, ERROR, time.time() + self.backoff)
                self.serverTrouble.emit(self.backoff)
                self._wake.wait(self.backoff)
                self._wake.clear()
                continue
            except Exception:
                self._set_status(t.path, ERROR, time.time() + BACKOFF_MAX)
                continue
            if self.backoff:
                self.backoff = 0
                self.serverTrouble.emit(0)
            self._set_status(t.path, classify(lyr))
            self.ready.emit(t.path, lyr)
            if used_network:
                self._stop.wait(CHECK_PAUSE)

    def cached(self, path: str):
        """(True, letra) si ya se buscó; (False, None) si no."""
        if path in self.memory:
            return True, self.memory[path]
        return False, None

    def request(self, track, force: bool = False):
        if track is None:
            return
        if not force and track.path in self.memory:
            self.ready.emit(track.path, self.memory[track.path])
            return
        with self.lock:
            if track.path in self.pending:
                return
            self.pending.add(track.path)
        threading.Thread(target=self._work, args=(track, force), daemon=True).start()

    def _work(self, track, force):
        try:
            lyr = load_lyrics(track, force)
        except LyricsNetworkError as e:
            # Queda pendiente: la revisión en segundo plano la reintentará sola.
            self._set_status(track.path, ERROR, time.time() + max(self.backoff, BACKOFF_MIN))
            self.failed.emit(track.path, str(e))
            return
        except Exception as e:  # nunca romper el reproductor por una letra
            self.failed.emit(track.path, f"Error al buscar la letra: {e}")
            return
        finally:
            with self.lock:
                self.pending.discard(track.path)
        self.memory[track.path] = lyr
        self._set_status(track.path, classify(lyr))
        self.ready.emit(track.path, lyr)

    def store_user_lyrics(self, track, lyr: Lyrics) -> str:
        """Guarda la letra escrita por el usuario y la deja lista para mostrarse."""
        where = save_user_lyrics(track, lyr)
        lyr.source = USER_SOURCE
        self.memory[track.path] = lyr
        self._set_status(track.path, classify(lyr))
        self.save_status()
        self.ready.emit(track.path, lyr)
        return where


# ---------------------------------------------------------------- letras del usuario

USER_DIR = LYRICS_DIR / "user"
USER_SOURCE = "Tu letra"


def _user_file(path: str, suffix: str) -> Path:
    return USER_DIR / (hashlib.md5(path.lower().encode("utf-8", "ignore")).hexdigest() + suffix)


def from_user_store(path: str) -> Lyrics | None:
    """Letra guardada por el usuario dentro de Sonora (instrumental o .lrc de respaldo)."""
    inst = _user_file(path, ".json")
    if inst.exists():
        try:
            return Lyrics.from_dict(json.loads(inst.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    lrc = _user_file(path, ".lrc")
    if lrc.exists():
        try:
            return from_text(lrc.read_text(encoding="utf-8"), USER_SOURCE)
        except OSError:
            pass
    return None


def format_lrc(lines: list) -> str:
    out = []
    for ms, text in lines:
        cs = round(ms / 10)
        m, rem = divmod(cs, 6000)
        s, c = divmod(rem, 100)
        out.append(f"[{m:02d}:{s:02d}.{c:02d}]{text}")
    return "\n".join(out)


def save_user_lyrics(track, lyr: Lyrics) -> str:
    """Guarda la letra del usuario y devuelve dónde quedó.

    Se escribe un .lrc junto a la canción (así también la ven otros reproductores); si la
    carpeta no lo permite, se guarda en la carpeta de datos de Sonora.
    """
    for f in (_user_file(track.path, ".json"), _user_file(track.path, ".lrc")):
        if f.exists():
            f.unlink()
    if lyr.instrumental:
        USER_DIR.mkdir(parents=True, exist_ok=True)
        data = Lyrics(source=USER_SOURCE, instrumental=True).to_dict()
        _user_file(track.path, ".json").write_text(json.dumps(data), encoding="utf-8")
        return "Sonora (marcada como instrumental)"
    text = format_lrc(lyr.lines) if lyr.synced else lyr.plain
    sidecar = Path(track.path).with_suffix(".lrc")
    try:
        sidecar.write_text(text, encoding="utf-8")
        return str(sidecar)
    except OSError:
        USER_DIR.mkdir(parents=True, exist_ok=True)
        _user_file(track.path, ".lrc").write_text(text, encoding="utf-8")
        return "la carpeta de datos de Sonora"


# ---------------------------------------------------------------- publicar en LRCLIB

class LyricsPublishError(Exception):
    pass


def _post(endpoint: str, body: bytes, headers: dict):
    req = urllib.request.Request(f"{API}/{endpoint}", data=body, method="POST",
                                 headers={"User-Agent": USER_AGENT, **headers})
    for attempt in range(4):
        _throttle()
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read().decode("utf-8")
                return resp.status, (json.loads(raw) if raw.strip() else None)
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < 3:
                time.sleep(_retry_after(e, attempt))
                continue
            try:
                info = json.loads(e.read().decode("utf-8"))
            except Exception:
                info = {}
            return e.code, info
        except (urllib.error.URLError, OSError) as e:
            raise LyricsPublishError("Sin conexión a internet") from e
    raise LyricsPublishError("LRCLIB está saturado; inténtalo más tarde")


def publish(meta: dict, plain: str, synced: str, progress=lambda msg: None, cancelled=lambda: False):
    """Publica una letra en LRCLIB. `meta`: trackName, artistName, albumName, duration."""
    from . import pow  # sin Qt: los procesos auxiliares lo cargan rápido
    body = json.dumps({**meta, "plainLyrics": plain, "syncedLyrics": synced},
                      ensure_ascii=False).encode("utf-8")
    for attempt in range(2):  # un reintento si la verificación caducó (dura 5 minutos)
        progress("Pidiendo la verificación a LRCLIB…")
        status, ch = _post("request-challenge", b"", {})
        if status != 200 or not ch or "prefix" not in ch:
            raise LyricsPublishError(f"LRCLIB no entregó la verificación (error {status})")
        progress("Resolviendo la verificación (suele tardar entre 10 y 30 s)…")
        nonce = pow.solve(ch["prefix"], ch["target"], cancelled)
        if nonce is None:
            raise LyricsPublishError("Publicación cancelada")
        progress("Publicando…")
        status, info = _post("publish", body, {"Content-Type": "application/json",
                                                "X-Publish-Token": f"{ch['prefix']}:{nonce}"})
        if status == 201:
            return
        if (info or {}).get("name") == "IncorrectPublishTokenError" and attempt == 0:
            continue
        message = (info or {}).get("message") or f"error {status}"
        raise LyricsPublishError(f"LRCLIB rechazó la publicación: {message}")


class Publisher(QObject):
    """Publica en segundo plano para no congelar la interfaz."""
    progress = Signal(str)
    done = Signal(bool, str)

    def __init__(self):
        super().__init__()
        self._cancel = False
        self.busy = False

    def start(self, meta: dict, plain: str, synced: str):
        self._cancel = False
        self.busy = True
        threading.Thread(target=self._run, args=(meta, plain, synced), daemon=True).start()

    def cancel(self):
        self._cancel = True

    def _run(self, meta, plain, synced):
        ok, message = True, "¡Publicada en LRCLIB! Gracias por contribuir."
        try:
            publish(meta, plain, synced, self.progress.emit, lambda: self._cancel)
        except LyricsPublishError as e:
            ok, message = False, str(e)
        except Exception as e:
            ok, message = False, f"Error inesperado al publicar: {e}"
        self.busy = False
        self.done.emit(ok, message)
