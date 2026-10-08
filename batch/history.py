"""Read a Spotify "Extended Streaming History" export and rank its tracks by plays."""
import json
import os
import re
import zipfile
from dataclasses import dataclass

REAL_PLAY_MS = 30_000
_HISTORY_FILE = re.compile(r"^Streaming_History_Audio_.*\.json$")
_TRACK_URI_PREFIX = "spotify:track:"


@dataclass
class Track:
    spotify_id: str
    track_name: str
    artist_name: str
    plays: int = 0
    ms: int = 0


def load_rows(path: str) -> list:
    """Load every play from a my_spotify_data.zip or from an extracted folder."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Not found: {path}")

    rows = []
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for name in sorted(archive.namelist()):
                if _HISTORY_FILE.match(os.path.basename(name)):
                    rows.extend(json.loads(archive.read(name)))
    else:
        for root, _, files in os.walk(path):
            for name in sorted(files):
                if _HISTORY_FILE.match(name):
                    with open(os.path.join(root, name), encoding="utf-8") as f:
                        rows.extend(json.load(f))

    if not rows:
        raise ValueError(f"No Streaming_History_Audio_*.json files in {path}")
    return rows


def aggregate(rows: list, since: int = 0) -> list:
    """Group plays by track, most-played first. A play counts when it lasted >= 30s."""
    tracks = {}
    for row in rows:
        uri = row.get("spotify_track_uri") or ""
        name = row.get("master_metadata_track_name")
        artist = row.get("master_metadata_album_artist_name")
        # Podcasts, audiobooks and local files have no track URI
        if not uri.startswith(_TRACK_URI_PREFIX) or not name or not artist:
            continue
        if since and int(str(row.get("ts", "0"))[:4]) < since:
            continue

        spotify_id = uri[len(_TRACK_URI_PREFIX):]
        track = tracks.get(spotify_id)
        if track is None:
            track = tracks[spotify_id] = Track(spotify_id, name, artist)
        ms_played = row.get("ms_played") or 0
        track.ms += ms_played
        if ms_played >= REAL_PLAY_MS:
            track.plays += 1

    return sorted(tracks.values(), key=lambda t: (-t.plays, -t.ms))


def select(tracks: list, min_plays: int = 1, limit: int = None) -> list:
    selected = [t for t in tracks if t.plays >= min_plays]
    return selected[:limit] if limit else selected
