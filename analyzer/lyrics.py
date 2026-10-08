"""Lyrics lookup: LRCLIB first, lyrics.ovh as a fallback (both free, no auth required)."""
import os
import re
import time
import unicodedata
from urllib.parse import quote

import requests

USER_AGENT = "music-analyzer (https://github.com/leitejoaov/music-analyzer)"
TIMEOUT_SECONDS = 8
MAX_CHARS = int(os.environ.get("LYRICS_MAX_CHARS", "3000"))
MIN_CHARS = 20
# LRCLIB answers 503 "server is busy, please retry" under load; give it a few chances
RETRY_STATUSES = {429, 502, 503, 504}
RETRY_WAITS_SECONDS = (1, 3)

# YouTube channel name patterns that sometimes end up in the artist field
_CHANNEL_SUFFIXES = re.compile(r"(?:VEVO|Official|Music|Records|TV|HQ|Oficial|4eva)$", re.I)
_DASH_SPLIT = re.compile(r"\s*[-–—]\s*")
_TITLE_NOISE = [
    re.compile(
        r"\s*[\(\[](Official\s*(Music\s*)?Video|Lyric\s*Video|Audio|Visualizer|Clipe\s*Oficial"
        r"|WebClipe|Unofficial\s*Video|Bass\s*Boosted|8D|Ao\s*Vivo|Live)[\)\]]",
        re.I,
    ),
    re.compile(r"\s*[\(\[].*?remix.*?[\)\]]", re.I),
    re.compile(r"\s*[\(\[].*?[\)\]]"),
    re.compile(r"\s*[-–]\s*(feat|ft)\.?\s*.*", re.I),
    re.compile(r"\s*[-–]\s*Ao\s*Vivo\s*$", re.I),
]


def clean_for_search(artist: str, title: str):
    """Strip noise ("(Official Video)", "feat. X", channel suffixes) before searching."""
    clean_artist = artist.strip()
    clean_title = title.strip()

    # "Artist - Song" or "Artist - Song - Channel" inside the title
    parts = _DASH_SPLIT.split(clean_title)
    if len(parts) >= 2:
        possible_artist, possible_title = parts[0].strip(), parts[1].strip()
        looks_like_channel = bool(_CHANNEL_SUFFIXES.search(clean_artist)) or "_" in clean_artist
        if looks_like_channel or (
            len(parts) >= 3 and len(possible_artist) > 1 and len(possible_title) > 1
        ):
            clean_artist, clean_title = possible_artist, possible_title

    for pattern in _TITLE_NOISE:
        clean_title = pattern.sub("", clean_title)
    clean_title = clean_title.strip()

    clean_artist = re.sub(r"VEVO$", "", clean_artist, flags=re.I)
    clean_artist = re.sub(r"\s*[\(\[].*?[\)\]]", "", clean_artist)
    clean_artist = clean_artist.replace("_", " ").strip()

    return clean_artist, clean_title


def normalize_name(name: str) -> str:
    """Lowercase, no accents, letters and digits only — for loose artist comparison."""
    decomposed = unicodedata.normalize("NFD", name)
    return "".join(ch for ch in decomposed if ch.isalnum()).lower()


def fetch_lyrics(artist: str, title: str):
    """Return (text, source) or None when no lyrics are found."""
    clean_artist, clean_title = clean_for_search(artist, title)
    if len(clean_artist) < 2 or len(clean_title) < 2:
        return None

    original_artist = artist.strip()
    artist_changed = clean_artist.lower() != original_artist.lower()

    for source, fetch in (("lrclib", _fetch_from_lrclib), ("lyrics.ovh", _fetch_from_lyrics_ovh)):
        text = fetch(clean_artist, clean_title)
        # If cleaning changed the artist, also try the original one
        if not text and artist_changed:
            text = fetch(original_artist, clean_title)
        if text:
            return text, source
    return None


def _get_json(url: str, **kwargs):
    """GET a JSON body, retrying when the server is busy or the request fails. None on failure."""
    for wait in (*RETRY_WAITS_SECONDS, None):
        try:
            response = requests.get(url, timeout=TIMEOUT_SECONDS, **kwargs)
            if getattr(response, "status_code", 200) not in RETRY_STATUSES:
                return response.json()
        except (requests.RequestException, ValueError):
            pass
        if wait is not None:
            time.sleep(wait)
    return None


def _fetch_from_lrclib(artist: str, title: str):
    data = _get_json(
        "https://lrclib.net/api/search",
        params={"track_name": title, "artist_name": artist},
        headers={"User-Agent": USER_AGENT},
    )
    if not isinstance(data, list):
        return None

    # Search is fuzzy, so only accept results credited to the artist we asked for
    wanted = normalize_name(artist)
    for item in data:
        text = item.get("plainLyrics") if isinstance(item, dict) else None
        if not isinstance(text, str) or len(text.strip()) <= MIN_CHARS:
            continue
        found = normalize_name(str(item.get("artistName") or ""))
        if found and (wanted in found or found in wanted):
            return text.strip()[:MAX_CHARS]
    return None


def _fetch_from_lyrics_ovh(artist: str, title: str):
    data = _get_json(f"https://api.lyrics.ovh/v1/{quote(artist, safe='')}/{quote(title, safe='')}")
    text = data.get("lyrics") if isinstance(data, dict) else None
    if isinstance(text, str) and len(text.strip()) > MIN_CHARS:
        return text.strip()[:MAX_CHARS]
    return None
