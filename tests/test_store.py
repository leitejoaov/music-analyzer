from batch.history import Track
from batch.store import Store

OK = {
    "audio": {"bpm": 120.0, "key": "C", "mode": "major", "mood_happy": 0.8},
    "audio_error": None,
    "lyrics": {"found": True, "source": "lrclib", "text": "some lyrics"},
}
BLOCKED = {
    "audio": None,
    "audio_error": "forbidden",
    "lyrics": {"found": True, "source": "lyrics.ovh", "text": "lyrics still came"},
}


def test_save_and_export(tmp_path):
    store = Store(str(tmp_path / "results.db"))
    store.save(Track("a", "Song A", "Artist", plays=3), OK)
    store.save(Track("b", "Song B", "Artist", plays=9), BLOCKED)

    exported = store.export()

    assert [r["spotify_id"] for r in exported] == ["b", "a"]
    assert exported[1] == {
        "spotify_id": "a",
        "track": "Song A",
        "artist": "Artist",
        "plays": 3,
        "audio": OK["audio"],
        "audio_error": None,
        "lyrics": OK["lyrics"],
    }
    assert exported[0]["audio"] is None
    assert exported[0]["audio_error"] == "forbidden"
    assert exported[0]["lyrics"]["text"] == "lyrics still came"


def test_status_follows_audio(tmp_path):
    store = Store(str(tmp_path / "results.db"))
    store.save(Track("a", "Song A", "Artist"), OK)
    store.save(Track("b", "Song B", "Artist"), BLOCKED)

    assert store.ids_with_status("done") == {"a"}
    assert store.ids_with_status("failed") == {"b"}


def test_retry_replaces_the_failed_row(tmp_path):
    path = str(tmp_path / "results.db")
    store = Store(path)
    store.save(Track("b", "Song B", "Artist"), BLOCKED)
    store.close()

    store = Store(path)  # reopening keeps the data
    store.save(Track("b", "Song B", "Artist"), OK)

    assert store.ids_with_status("failed") == set()
    assert store.ids_with_status("done") == {"b"}
    assert len(store.export()) == 1
