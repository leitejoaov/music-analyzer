import pytest
import requests

from analyzer import lyrics


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


LONG_TEXT = "la la la, this is long enough to count as lyrics"


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(lyrics.time, "sleep", lambda seconds: None)


def fake_get(routes):
    """Build a requests.get replacement; `routes` maps a URL prefix to a payload or an exception."""
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs.get("params")))
        for prefix, payload in routes.items():
            if url.startswith(prefix):
                if isinstance(payload, Exception):
                    raise payload
                return FakeResponse(payload)
        raise AssertionError(f"unexpected request: {url}")

    get.calls = calls
    return get


def test_clean_for_search_strips_title_noise():
    assert lyrics.clean_for_search("Joji", "CAN'T GET OVER YOU (feat. Clams Casino)") == ("Joji", "CAN'T GET OVER YOU")
    assert lyrics.clean_for_search("Frou Frou", "a new kind of love - feat. Someone") == ("Frou Frou", "a new kind of love")
    assert lyrics.clean_for_search("Banda", "Musica [Ao Vivo]") == ("Banda", "Musica")


def test_clean_for_search_uses_artist_from_title_for_channel_names():
    assert lyrics.clean_for_search("ArtistVEVO", "Artist - Song (Official Video)") == ("Artist", "Song")
    assert lyrics.clean_for_search("some_channel", "Real Artist - Real Song") == ("Real Artist", "Real Song")


def test_clean_for_search_keeps_regular_names():
    assert lyrics.clean_for_search(" The Neighbourhood ", " Sweater Weather ") == ("The Neighbourhood", "Sweater Weather")


def test_normalize_name():
    assert lyrics.normalize_name("Beyoncé & JAY-Z") == "beyoncejayz"
    assert lyrics.normalize_name("Ólafur Arnalds") == "olafurarnalds"


def test_lrclib_accepts_matching_artist(monkeypatch):
    get = fake_get({"https://lrclib.net": [{"artistName": "Kali Uchis", "plainLyrics": LONG_TEXT}]})
    monkeypatch.setattr(lyrics.requests, "get", get)

    assert lyrics.fetch_lyrics("Kali Uchis", "telepatía") == (LONG_TEXT, "lrclib")
    assert get.calls[0][1] == {"track_name": "telepatía", "artist_name": "Kali Uchis"}


def test_lrclib_accepts_artist_with_features(monkeypatch):
    payload = [{"artistName": "G-Eazy feat. Christoph Andersson", "plainLyrics": LONG_TEXT}]
    monkeypatch.setattr(lyrics.requests, "get", fake_get({"https://lrclib.net": payload}))

    assert lyrics.fetch_lyrics("G-Eazy", "Tumblr Girls") == (LONG_TEXT, "lrclib")


def test_lrclib_rejects_other_artist_and_falls_back(monkeypatch):
    get = fake_get(
        {
            "https://lrclib.net": [{"artistName": "Someone Else", "plainLyrics": LONG_TEXT}],
            "https://api.lyrics.ovh": {"lyrics": "from the fallback source, long enough"},
        }
    )
    monkeypatch.setattr(lyrics.requests, "get", get)

    assert lyrics.fetch_lyrics("Verzache", "Mind Games") == ("from the fallback source, long enough", "lyrics.ovh")


def test_lrclib_skips_instrumental_and_short_entries(monkeypatch):
    payload = [
        {"artistName": "Vansire", "plainLyrics": None, "instrumental": True},
        {"artistName": "Vansire", "plainLyrics": "too short"},
        {"artistName": "Vansire", "plainLyrics": LONG_TEXT},
    ]
    monkeypatch.setattr(lyrics.requests, "get", fake_get({"https://lrclib.net": payload}))

    assert lyrics.fetch_lyrics("Vansire", "Metamodernity") == (LONG_TEXT, "lrclib")


def test_not_found_anywhere(monkeypatch):
    get = fake_get({"https://lrclib.net": [], "https://api.lyrics.ovh": {"error": "No lyrics found"}})
    monkeypatch.setattr(lyrics.requests, "get", get)

    assert lyrics.fetch_lyrics("Nobody", "Nothing") is None


def test_network_errors_count_as_not_found(monkeypatch):
    get = fake_get(
        {
            "https://lrclib.net": requests.ConnectionError("down"),
            "https://api.lyrics.ovh": requests.Timeout("slow"),
        }
    )
    monkeypatch.setattr(lyrics.requests, "get", get)

    assert lyrics.fetch_lyrics("Nobody", "Nothing") is None


def test_text_is_truncated(monkeypatch):
    payload = [{"artistName": "Artist", "plainLyrics": "a" * 10_000}]
    monkeypatch.setattr(lyrics.requests, "get", fake_get({"https://lrclib.net": payload}))

    text, _ = lyrics.fetch_lyrics("Artist", "Song")
    assert len(text) == lyrics.MAX_CHARS


def test_too_short_names_are_not_searched(monkeypatch):
    monkeypatch.setattr(lyrics.requests, "get", fake_get({}))

    assert lyrics.fetch_lyrics("A", "B") is None


def test_retries_when_lrclib_is_busy(monkeypatch):
    busy = FakeResponse({"name": "ServerOverloaded", "statusCode": 503}, status_code=503)
    answers = [busy, busy, FakeResponse([{"artistName": "Verzache", "plainLyrics": LONG_TEXT}])]
    monkeypatch.setattr(lyrics.requests, "get", lambda url, **kwargs: answers.pop(0))

    assert lyrics.fetch_lyrics("Verzache", "What Happened") == (LONG_TEXT, "lrclib")
    assert answers == []


def test_gives_up_after_three_busy_answers(monkeypatch):
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        return FakeResponse({"statusCode": 503}, status_code=503)

    monkeypatch.setattr(lyrics.requests, "get", get)

    assert lyrics.fetch_lyrics("Verzache", "What Happened") is None
    assert len(calls) == 6  # three tries on each source
