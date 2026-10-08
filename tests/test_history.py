import json
import zipfile

import pytest

from batch.history import aggregate, load_rows, select


def play(track_id, name="Song", artist="Artist", ms=60_000, ts="2020-01-01T00:00:00Z"):
    return {
        "ts": ts,
        "ms_played": ms,
        "master_metadata_track_name": name,
        "master_metadata_album_artist_name": artist,
        "spotify_track_uri": f"spotify:track:{track_id}" if track_id else None,
    }


def test_only_plays_of_30s_or_more_count():
    tracks = aggregate([play("a", ms=29_999), play("a", ms=30_000), play("a", ms=200_000)])

    assert len(tracks) == 1
    assert tracks[0].plays == 2
    assert tracks[0].ms == 259_999


def test_most_played_first_then_most_listened():
    rows = [play("a"), play("b"), play("b"), play("c", ms=90_000)]

    assert [t.spotify_id for t in aggregate(rows)] == ["b", "c", "a"]


def test_skips_podcasts_and_rows_without_metadata():
    rows = [play(None), play("a", name=None), play("b", artist=None), play("c")]

    assert [t.spotify_id for t in aggregate(rows)] == ["c"]


def test_since_filters_by_year():
    rows = [play("old", ts="2015-06-01T00:00:00Z"), play("new", ts="2021-06-01T00:00:00Z")]

    assert [t.spotify_id for t in aggregate(rows, since=2020)] == ["new"]


def test_select_applies_min_plays_and_limit():
    tracks = aggregate([play("a"), play("a"), play("a"), play("b"), play("b"), play("c")])

    assert [t.spotify_id for t in select(tracks, min_plays=2)] == ["a", "b"]
    assert [t.spotify_id for t in select(tracks, limit=1)] == ["a"]


def test_load_rows_from_zip(tmp_path):
    path = tmp_path / "my_spotify_data.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("Spotify Extended Streaming History/Streaming_History_Audio_2020.json", json.dumps([play("a")]))
        archive.writestr("Spotify Extended Streaming History/Streaming_History_Audio_2021_1.json", json.dumps([play("b")]))
        archive.writestr("Spotify Extended Streaming History/Streaming_History_Video_2021.json", json.dumps([play("v")]))
        archive.writestr("Spotify Extended Streaming History/ReadMeFirst.pdf", "not json")

    assert [r["spotify_track_uri"] for r in load_rows(str(path))] == ["spotify:track:a", "spotify:track:b"]


def test_load_rows_from_folder(tmp_path):
    folder = tmp_path / "export" / "nested"
    folder.mkdir(parents=True)
    (folder / "Streaming_History_Audio_2020.json").write_text(json.dumps([play("a")]))

    assert len(load_rows(str(tmp_path / "export"))) == 1


def test_load_rows_errors(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_rows(str(tmp_path / "missing.zip"))
    with pytest.raises(ValueError):
        load_rows(str(tmp_path))
