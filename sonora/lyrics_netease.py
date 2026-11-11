"""Fuente de letras opcional: NetEase Cloud Music (网易云音乐).

Desactivada por defecto. Usa la API web NO oficial que también usan varios reproductores de
código abierto: puede cambiar o bloquearse sin aviso, por eso sólo se usa como respaldo de
LRCLIB (cuando LRCLIB no tiene la letra o no responde). Casi todas sus letras están sincronizadas.
"""
import json
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

SEARCH = "https://music.163.com/api/cloudsearch/pc"
LYRIC = "https://music.163.com/api/song/lyric"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Referer": "https://music.163.com/"}
MIN_INTERVAL = 1.2
DURATION_TOLERANCE = 4   # segundos

# Líneas de créditos que NetEase mezcla con la letra (letrista, compositor, quien la subió…).
_CREDIT = re.compile(r"^\s*(作词|作曲|编曲|制作人|监制|混音|母带|和声|吉他|贝斯|鼓|录音|出品|发行|词|曲|演唱|"
                     r"edit(ed)?\s+by|lrc\s+by|lyrics?\s+by|written\s+by|composed\s+by|produced\s+by)\b\s*[:：]?",
                     re.IGNORECASE)
_PURE = re.compile(r"纯音乐|請欣賞|请欣赏")
_TIME = re.compile(r"^((?:\[\d{1,3}:\d{1,2}(?:[.:]\d{1,3})?\])+)(.*)$")

_lock = threading.Lock()
_last = 0.0


class NetEaseError(Exception):
    pass


def _get(url: str, params: dict) -> dict:
    global _last
    with _lock:
        wait = _last + MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last = time.monotonic()
    req = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}", headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise NetEaseError("NetEase no responde") from e
    if data.get("code") not in (200, None):   # p. ej. 406 «operación demasiado frecuente»
        raise NetEaseError(f"NetEase rechazó la consulta (código {data.get('code')})")
    return data


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _artist_match(ours: str, theirs: list) -> bool:
    a = _norm(ours)
    return bool(a) and any(a in _norm(x.get("name", "")) or _norm(x.get("name", "")) in a
                           for x in theirs if x.get("name"))


def clean_lrc(lrc: str) -> str:
    """Quita créditos y metadatos; devuelve un LRC sólo con la letra."""
    out = []
    for raw in lrc.splitlines():
        m = _TIME.match(raw.strip())
        if not m:
            continue
        text = m.group(2).strip()
        if text and _CREDIT.match(text):
            continue
        out.append(m.group(1) + text)
    return "\n".join(out)


def fetch(track, base_title: str):
    """(texto LRC, instrumental) o None si NetEase no la tiene. Lanza NetEaseError si no responde."""
    artist = track.artists[0] if track.artist else ""
    if not artist:
        return None
    data = _get(SEARCH, {"s": f"{base_title} {artist}", "type": 1, "limit": 10})
    songs = (data.get("result") or {}).get("songs") or []
    dur = track.duration or 0
    candidates = [s for s in songs
                  if _artist_match(artist, s.get("ar", []))
                  and (not dur or abs(s.get("dt", 0) / 1000 - dur) <= DURATION_TOLERANCE)]
    if not candidates:
        return None
    title = _norm(base_title)
    candidates.sort(key=lambda s: (title not in _norm(s.get("name", "")), abs(s.get("dt", 0) / 1000 - dur)))
    lyr = _get(LYRIC, {"id": candidates[0]["id"], "lv": 1, "kv": 1, "tv": -1})
    lrc = (lyr.get("lrc") or {}).get("lyric") or ""
    if lyr.get("pureMusic") or (_PURE.search(lrc) and len(lrc) < 200):
        return "", True
    cleaned = clean_lrc(lrc)
    if len([ln for ln in cleaned.splitlines() if _TIME.match(ln) and _TIME.match(ln).group(2)]) < 3:
        return None
    return cleaned, False
