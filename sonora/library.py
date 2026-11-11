"""Biblioteca: lectura de metadatos, carátulas, escaneo de carpetas y persistencia."""
import base64
import hashlib
import json
import os
import re
import struct
import time
import unicodedata
from dataclasses import asdict, dataclass, field, fields
from functools import lru_cache
from pathlib import Path

import mutagen
from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QImage

AUDIO_EXTS = {
    ".mp3", ".flac", ".wav", ".ogg", ".oga", ".opus", ".m4a", ".m4b", ".aac", ".mp4",
    ".wma", ".aiff", ".aif", ".aifc", ".alac", ".ape", ".wv", ".mka", ".webm", ".ac3",
    ".dts", ".mpc", ".amr", ".3gp", ".caf", ".mp2", ".tta",
}
FOLDER_ART = ("cover.jpg", "folder.jpg", "front.jpg", "albumart.jpg", "cover.png", "folder.png", "front.png")

APP_VERSION = "2.1"
_APPDATA = Path(os.environ.get("APPDATA") or Path.home())
APP_DIR = _APPDATA / "Sonora2"
V1_DIR = _APPDATA / "Sonora"   # datos de Sonora 1.0: sólo se leen, nunca se modifican
COVERS_DIR = APP_DIR / "covers"
LIB_FILE = APP_DIR / "library.json"


def _migrate_from_v1():
    """Primera ejecución de Sonora 2: copia biblioteca, carátulas y preferencias de la 1.0."""
    if APP_DIR.exists() or not (V1_DIR / "library.json").exists():
        return
    import shutil
    COVERS_DIR.mkdir(parents=True, exist_ok=True)
    if (V1_DIR / "covers").is_dir():
        for f in (V1_DIR / "covers").iterdir():
            shutil.copy2(f, COVERS_DIR / f.name)
    if (V1_DIR / "settings.ini").exists():
        shutil.copy2(V1_DIR / "settings.ini", APP_DIR / "settings.ini")
    try:
        data = json.loads((V1_DIR / "library.json").read_text(encoding="utf-8"))
        for t in data.get("tracks", []):
            if t.get("cover"):  # apuntar a la copia de la carátula en la carpeta de la v2
                copied = COVERS_DIR / Path(t["cover"]).name
                if copied.exists():
                    t["cover"] = str(copied)
        LIB_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except (OSError, ValueError):
        pass


_migrate_from_v1()
COVERS_DIR.mkdir(parents=True, exist_ok=True)

_ARTIST_SPLIT = re.compile(r"\s*(?:,|;|/|\bfeat\.?|\bft\.|\bfeaturing\b)\s*", re.IGNORECASE)


def is_audio(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in AUDIO_EXTS


@dataclass
class Track:
    path: str
    title: str
    artist: str = ""
    album: str = ""
    album_artist: str = ""
    year: str = ""
    track_no: int = 0
    disc_no: int = 0
    duration: float = 0.0
    cover: str = ""
    added: float = 0.0
    mtime: float = 0.0

    @property
    def artist_display(self) -> str:
        return self.artist or "Artista desconocido"

    @property
    def album_display(self) -> str:
        return self.album or "Álbum desconocido"

    @property
    def album_key(self) -> str:
        return f"{(self.album_artist or self.artist).lower()}|{self.album.lower()}"

    @property
    def artists(self) -> list[str]:
        parts = [a.strip() for a in _ARTIST_SPLIT.split(self.artist) if a.strip()]
        return parts or ["Artista desconocido"]

    def matches(self, text: str) -> bool:
        return text in f"{self.title}\n{self.artist}\n{self.album}".lower()


# ---------------------------------------------------------------- metadatos

def _val(tags, keys) -> str:
    if not tags:
        return ""
    for k in keys:
        try:
            v = tags.get(k)
        except Exception:
            v = None
        if v is None:
            continue
        if hasattr(v, "text"):
            v = v.text
        if isinstance(v, (list, tuple)):
            if not v:
                continue
            v = v[0]
        if hasattr(v, "value"):
            v = v.value
        if isinstance(v, tuple):
            v = v[0]
        s = str(v).strip()
        if s:
            return s
    return ""


def _num(s: str) -> int:
    m = re.match(r"\s*(\d+)", s or "")
    return int(m.group(1)) if m else 0


def _asf_picture(raw: bytes):
    # WM/Picture: tipo(1) tamaño(4) mime(utf16\0) descripción(utf16\0) datos
    pos = 5
    for _ in range(2):
        while raw[pos:pos + 2] != b"\x00\x00":
            pos += 2
        pos += 2
    size = struct.unpack_from("<I", raw, 1)[0]
    return raw[pos:pos + size]


def _cover_bytes(audio):
    try:
        pics = getattr(audio, "pictures", None)
        if pics:
            return pics[0].data
        tags = audio.tags
        if tags is None:
            return None
        if hasattr(tags, "getall"):
            apic = tags.getall("APIC")
            if apic:
                return apic[0].data
        covr = tags.get("covr")
        if covr:
            return bytes(covr[0])
        mbp = tags.get("metadata_block_picture")
        if mbp:
            from mutagen.flac import Picture
            return Picture(base64.b64decode(mbp[0])).data
        wm = tags.get("WM/Picture")
        if wm:
            return _asf_picture(bytes(wm[0].value))
        ape = tags.get("Cover Art (Front)")
        if ape:
            raw = bytes(ape.value)
            return raw[raw.index(b"\x00") + 1:]
    except Exception:
        return None
    return None


def _store_cover(data: bytes | None, key: str, folder_art: str | None) -> str:
    dest = COVERS_DIR / (hashlib.md5(key.encode("utf-8", "ignore")).hexdigest() + ".jpg")
    if dest.exists():
        return str(dest)
    if data and data[:3] == b"\xff\xd8\xff" and len(data) < 400_000:
        dest.write_bytes(data)  # ya es un JPEG de tamaño razonable: sin re-codificar
        return str(dest)
    img = QImage()
    if data:
        img.loadFromData(data)
    if img.isNull() and folder_art:
        img.load(folder_art)
    if img.isNull():
        return ""
    if img.width() > 600 or img.height() > 600:
        img = img.scaled(600, 600, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    img.save(str(dest), "JPG", 90)
    return str(dest)


def find_folder_art(directory: str) -> str | None:
    try:
        names = {n.lower(): n for n in os.listdir(directory)}
    except OSError:
        return None
    for cand in FOLDER_ART:
        if cand in names:
            return os.path.join(directory, names[cand])
    return None


def read_track(path: str, mtime: float | None = None, folder_art: str | None = "auto") -> Track:
    path = os.path.normpath(path)
    if mtime is None:
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = 0.0
    t = Track(path=path, title=Path(path).stem, added=time.time(), mtime=mtime)
    try:
        audio = mutagen.File(path)
    except Exception:
        audio = None
    data = None
    if audio is not None:
        info = getattr(audio, "info", None)
        t.duration = float(getattr(info, "length", 0) or 0)
        tags = audio.tags
        t.title = _val(tags, ["TIT2", "title", "\xa9nam", "Title"]) or t.title
        t.artist = _val(tags, ["TPE1", "artist", "\xa9ART", "Author", "Artist"])
        t.album = _val(tags, ["TALB", "album", "\xa9alb", "WM/AlbumTitle", "Album"])
        t.album_artist = _val(tags, ["TPE2", "albumartist", "aART", "WM/AlbumArtist", "Album Artist"])
        t.year = _val(tags, ["TDRC", "TYER", "date", "year", "\xa9day", "WM/Year", "Year"])[:4]
        t.track_no = _num(_val(tags, ["TRCK", "tracknumber", "trkn", "WM/TrackNumber", "Track"]))
        t.disc_no = _num(_val(tags, ["TPOS", "discnumber", "disk", "WM/PartOfSet", "Disc"]))
        data = _cover_bytes(audio)
    if folder_art == "auto":
        folder_art = find_folder_art(os.path.dirname(path))
    key = t.album_key if t.album else path
    t.cover = _store_cover(data, key, folder_art)
    return t


# ---------------------------------------------------------------- agrupaciones

@dataclass
class Group:
    key: str
    name: str
    subtitle: str
    cover: str = ""
    year: str = ""
    tracks: list = field(default_factory=list)


def group_albums(tracks) -> list[Group]:
    d: dict[str, Group] = {}
    for t in tracks:
        g = d.get(t.album_key)
        if g is None:
            g = d[t.album_key] = Group(t.album_key, t.album_display, t.album_artist or t.artist_display)
        g.tracks.append(t)
        if not g.cover and t.cover:
            g.cover = t.cover
        if not g.year and t.year:
            g.year = t.year
    for g in d.values():
        g.tracks.sort(key=lambda t: (t.disc_no, t.track_no, t.title.lower()))
    return sorted(d.values(), key=lambda g: g.name.lower())


def group_folders(tracks) -> list[Group]:
    d: dict[str, Group] = {}
    for t in tracks:
        k = os.path.dirname(t.path)
        g = d.get(k)
        if g is None:
            g = d[k] = Group(k, os.path.basename(k) or k, "")
        g.tracks.append(t)
        if not g.cover and t.cover:
            g.cover = t.cover
    for g in d.values():
        n = len(g.tracks)
        g.subtitle = f"{n} canción" if n == 1 else f"{n} canciones"
    return sorted(d.values(), key=lambda g: natural(g.name))


_DIGITS = re.compile(r"(\d+)")


@lru_cache(maxsize=50000)
def natural(s: str) -> tuple:
    """Clave de orden «natural»: sin tildes, sin mayúsculas y con números como números (2 < 10)."""
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return tuple(int(p) if p.isdigit() else p for p in _DIGITS.split(s))


def group_artists(tracks) -> list[Group]:
    d: dict[str, Group] = {}
    for t in tracks:
        for name in t.artists:
            k = name.lower()
            g = d.get(k)
            if g is None:
                g = d[k] = Group(name, name, "")
            g.tracks.append(t)
            if not g.cover and t.cover:
                g.cover = t.cover
    for g in d.values():
        n = len(g.tracks)
        g.subtitle = f"{n} canción" if n == 1 else f"{n} canciones"
        g.tracks.sort(key=lambda t: (t.year, t.album.lower(), t.disc_no, t.track_no))
    return sorted(d.values(), key=lambda g: g.name.lower())


# ---------------------------------------------------------------- biblioteca

class Library:
    def __init__(self):
        self.tracks: dict[str, Track] = {}
        self.folders: list[str] = []
        self.first_run = not LIB_FILE.exists()
        self.load()

    def load(self):
        if not LIB_FILE.exists():
            return
        try:
            data = json.loads(LIB_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        names = {f.name for f in fields(Track)}
        self.folders = data.get("folders", [])
        for d in data.get("tracks", []):
            t = Track(**{k: v for k, v in d.items() if k in names})
            self.tracks[t.path] = t

    def save(self):
        data = {"folders": self.folders, "tracks": [asdict(t) for t in self.tracks.values()]}
        tmp = LIB_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, LIB_FILE)

    def add(self, tracks):
        for t in tracks:
            old = self.tracks.get(t.path)
            if old is not None:
                t.added = old.added
            self.tracks[t.path] = t

    def remove(self, paths):
        for p in paths:
            self.tracks.pop(p, None)

    def remove_folder(self, folder: str):
        self.folders = [f for f in self.folders if f != folder]
        prefix = os.path.normcase(folder.rstrip("\\/") + os.sep)
        still = [os.path.normcase(f.rstrip("\\/") + os.sep) for f in self.folders]
        for p in list(self.tracks):
            np = os.path.normcase(p)
            if np.startswith(prefix) and not any(np.startswith(s) for s in still):
                del self.tracks[p]

    def all(self) -> list[Track]:
        return list(self.tracks.values())


class Scanner(QThread):
    """Escanea carpetas en segundo plano; sólo lee archivos nuevos o modificados."""
    batch = Signal(list)
    progress = Signal(int)
    finished_scan = Signal(list)  # rutas que ya no existen

    def __init__(self, folders, known: dict[str, float]):
        super().__init__()
        self.folders = [os.path.normpath(f) for f in folders]
        self.known = known

    def run(self):
        seen, pending, count = set(), [], 0
        art_cache: dict[str, str | None] = {}
        for folder in self.folders:
            for root, _dirs, files in os.walk(folder):
                if self.isInterruptionRequested():
                    return
                for name in files:
                    if os.path.splitext(name)[1].lower() not in AUDIO_EXTS:
                        continue
                    path = os.path.normpath(os.path.join(root, name))
                    try:
                        st = os.stat(path)
                    except OSError:
                        continue
                    if st.st_size == 0:  # descarga fallida/archivo vacío: no es reproducible
                        continue
                    seen.add(path)
                    mtime = st.st_mtime
                    if self.known.get(path) == mtime:
                        continue
                    if root not in art_cache:
                        art_cache[root] = find_folder_art(root)
                    pending.append(read_track(path, mtime, art_cache[root]))
                    count += 1
                    if len(pending) >= 40:
                        self.batch.emit(pending)
                        pending = []
                        self.progress.emit(count)
        if pending:
            self.batch.emit(pending)
        self.progress.emit(count)
        prefixes = [os.path.normcase(f.rstrip("\\/") + os.sep) for f in self.folders]
        removed = [p for p in self.known if p not in seen
                   and any(os.path.normcase(p).startswith(pre) for pre in prefixes)]
        self.finished_scan.emit(removed)
