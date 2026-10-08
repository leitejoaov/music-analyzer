"""Analysis results in a single SQLite file, so a batch can be interrupted and resumed."""
import json
import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    spotify_id    TEXT PRIMARY KEY,
    track_name    TEXT NOT NULL,
    artist_name   TEXT NOT NULL,
    plays         INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL,          -- 'done' (has audio) or 'failed' (no audio)
    audio         TEXT,                   -- JSON object with the audio features
    audio_error   TEXT,
    lyrics_found  INTEGER NOT NULL DEFAULT 0,
    lyrics_source TEXT,
    lyrics_text   TEXT,
    analyzed_at   TEXT NOT NULL DEFAULT (datetime('now'))
)
"""


class Store:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(_SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()

    def ids_with_status(self, status: str) -> set:
        rows = self.conn.execute("SELECT spotify_id FROM tracks WHERE status = ?", (status,))
        return {row["spotify_id"] for row in rows}

    def save(self, track, result: dict):
        """Store one /analyze response. `track` is a batch.history.Track."""
        audio = result.get("audio")
        lyrics = result.get("lyrics") or {}
        self.conn.execute(
            """
            INSERT INTO tracks (spotify_id, track_name, artist_name, plays, status, audio,
                                audio_error, lyrics_found, lyrics_source, lyrics_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (spotify_id) DO UPDATE SET
                track_name = excluded.track_name, artist_name = excluded.artist_name,
                plays = excluded.plays, status = excluded.status, audio = excluded.audio,
                audio_error = excluded.audio_error, lyrics_found = excluded.lyrics_found,
                lyrics_source = excluded.lyrics_source, lyrics_text = excluded.lyrics_text,
                analyzed_at = datetime('now')
            """,
            (
                track.spotify_id,
                track.track_name,
                track.artist_name,
                track.plays,
                "done" if audio else "failed",
                json.dumps(audio) if audio else None,
                result.get("audio_error"),
                int(bool(lyrics.get("found"))),
                lyrics.get("source"),
                lyrics.get("text"),
            ),
        )
        self.conn.commit()

    def export(self) -> list:
        """Every stored track, most-played first, in the same shape as the /analyze response."""
        rows = self.conn.execute("SELECT * FROM tracks ORDER BY plays DESC, spotify_id")
        return [
            {
                "spotify_id": row["spotify_id"],
                "track": row["track_name"],
                "artist": row["artist_name"],
                "plays": row["plays"],
                "audio": json.loads(row["audio"]) if row["audio"] else None,
                "audio_error": row["audio_error"],
                "lyrics": {
                    "found": bool(row["lyrics_found"]),
                    "source": row["lyrics_source"],
                    "text": row["lyrics_text"],
                },
            }
            for row in rows
        ]
