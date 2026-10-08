import json

import requests

from batch import import_history
from batch.history import Track
from batch.import_history import analyze_with_retry

TRACK = Track("a", "Song", "Artist", plays=5)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


def scripted(*steps):
    """A `post` that returns (or raises) each step in order."""
    remaining = list(steps)

    def post(payload):
        step = remaining.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    return post


def result(audio_error=None, audio=None):
    return {"audio": audio, "audio_error": audio_error, "lyrics": {"found": False, "source": None, "text": None}}


def run(post):
    waits = []
    outcome = analyze_with_retry(post, TRACK, sleep=waits.append, log=lambda _: None)
    return outcome, waits


def test_returns_the_response_as_is():
    ok = result(audio={"bpm": 120})

    assert run(scripted(FakeResponse(ok))) == (ok, [])


def test_blocked_download_is_a_normal_failure_not_a_retry():
    blocked = result("forbidden")

    assert run(scripted(FakeResponse(blocked))) == (blocked, [])


def test_waits_and_retries_the_same_track_when_the_analyzer_is_unreachable():
    ok = result(audio={"bpm": 120})
    post = scripted(requests.ConnectionError(), requests.ConnectionError(), FakeResponse(ok))

    assert run(post) == (ok, [30, 60])


def test_waits_and_retries_when_the_analyzer_has_no_internet():
    ok = result(audio={"bpm": 120})
    post = scripted(FakeResponse(result("network")), FakeResponse(ok))

    assert run(post) == (ok, [30])


def test_wait_doubles_up_to_five_minutes():
    post = scripted(*[requests.ConnectionError()] * 6, FakeResponse(result("not_found")))

    assert run(post)[1] == [30, 60, 120, 240, 300, 300]


def test_read_timeout_and_server_errors_fail_the_track():
    assert run(scripted(requests.ReadTimeout()))[0]["audio_error"] == "timeout"
    assert run(scripted(FakeResponse({}, status_code=500)))[0]["audio_error"] == "service_error"


def test_export_command(tmp_path, capsys):
    from batch.store import Store

    db, out = str(tmp_path / "results.db"), str(tmp_path / "results.json")
    store = Store(db)
    store.save(TRACK, result(audio={"bpm": 120}))
    store.close()

    assert import_history.main(["export", "--db", db, "--out", out]) == 0
    assert json.load(open(out))[0]["spotify_id"] == "a"
    assert "1 tracks (1 with audio, 0 with lyrics)" in capsys.readouterr().out


def test_missing_input_exits_with_a_message(tmp_path, capsys):
    assert import_history.main([str(tmp_path / "missing.zip")]) == 1
    assert "Not found" in capsys.readouterr().out
