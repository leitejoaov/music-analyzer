"""Send every track of a Spotify export through the analyzer and store the results.

Usage:
    python -m batch.import_history <my_spotify_data.zip | folder> [options]
    python -m batch.import_history export [--db results.db] [--out results.json]

Interrupt it at any time and run the same command again: it resumes where it stopped.
"""
import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from .history import aggregate, load_rows, select
from .store import Store

DEFAULT_URL = "http://127.0.0.1:5001"
# A track normally takes ~15s; allow for a slow download before giving up on it
REQUEST_TIMEOUT_SECONDS = 330
FIRST_WAIT_SECONDS = 30
MAX_WAIT_SECONDS = 300


def analyze_with_retry(post, track, sleep=time.sleep, log=print) -> dict:
    """Call the analyzer for one track and return the result to store.

    When the service is unreachable or reports that the network is down, wait and try the same
    track again instead of failing it — otherwise an internet outage burns through the whole list.
    """
    wait = FIRST_WAIT_SECONDS
    while True:
        try:
            response = post({"track": track.track_name, "artist": track.artist_name})
        except requests.ReadTimeout:
            return _failure("timeout")
        except requests.ConnectionError:
            reason = "analyzer unreachable"
        else:
            if response.status_code != 200:
                return _failure("service_error")
            result = response.json()
            if result.get("audio_error") != "network":
                return result
            reason = "no internet in the analyzer"

        log(f"[import] {reason}; waiting {wait}s before retrying {track.track_name}")
        sleep(wait)
        wait = min(wait * 2, MAX_WAIT_SECONDS)


def _failure(audio_error: str) -> dict:
    return {
        "audio": None,
        "audio_error": audio_error,
        "lyrics": {"found": False, "source": None, "text": None},
    }


def run_import(args) -> int:
    rows = load_rows(args.input)
    tracks = aggregate(rows, since=args.since)
    selected = select(tracks, min_plays=args.min_plays, limit=args.limit)
    print(f"[import] {len(rows)} plays, {len(tracks)} unique tracks, {len(selected)} after filters")

    if args.dry_run:
        print("[import] top 10:")
        for t in selected[:10]:
            print(f"  {t.plays}x  {t.track_name} - {t.artist_name}")
        return 0

    try:
        health = requests.get(f"{args.url}/health", timeout=10).json()
    except (requests.RequestException, ValueError):
        print(f"[import] analyzer is not responding at {args.url} — run `docker compose up -d` first")
        return 1
    print(f"[import] analyzer ok, {health.get('tf_models_loaded')} mood models loaded")

    store = Store(args.db)
    skip = store.ids_with_status("done")
    if not args.retry_failed:
        skip |= store.ids_with_status("failed")
    todo = [t for t in selected if t.spotify_id not in skip]
    print(f"[import] {len(selected) - len(todo)} already processed, {len(todo)} to go")

    def post(payload):
        return requests.post(f"{args.url}/analyze", json=payload, timeout=REQUEST_TIMEOUT_SECONDS)

    done = failed = 0
    started = time.time()
    pool = ThreadPoolExecutor(max_workers=args.concurrency)
    try:
        futures = {pool.submit(analyze_with_retry, post, t): t for t in todo}
        for future in as_completed(futures):
            track, result = futures[future], future.result()
            store.save(track, result)
            if result.get("audio"):
                done += 1
            else:
                failed += 1
                print(f"[import] failed ({result.get('audio_error')}): {track.track_name} - {track.artist_name}")

            total = done + failed
            if total % 10 == 0 or total == len(todo):
                # Wall-clock time per finished track, so concurrency is already accounted for
                eta_min = round((len(todo) - total) * (time.time() - started) / total / 60)
                print(f"[import] {total}/{len(todo)} (ok {done}, failed {failed}) — ETA ~{eta_min} min")
    except KeyboardInterrupt:
        pool.shutdown(wait=False, cancel_futures=True)
        print("\n[import] interrupted — run the same command again to resume")
        return 130
    finally:
        store.close()

    pool.shutdown()
    print(f"[import] finished: {done} analyzed, {failed} failed (retry those with --retry-failed)")
    return 0


def run_export(args) -> int:
    store = Store(args.db)
    try:
        results = store.export()
    finally:
        store.close()
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    with_audio = sum(1 for r in results if r["audio"])
    with_lyrics = sum(1 for r in results if r["lyrics"]["found"])
    print(f"[export] {len(results)} tracks ({with_audio} with audio, {with_lyrics} with lyrics) -> {args.out}")
    return 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv

    if argv and argv[0] == "export":
        parser = argparse.ArgumentParser(prog="python -m batch.import_history export")
        parser.add_argument("--db", default="results.db")
        parser.add_argument("--out", default="results.json")
        return run_export(parser.parse_args(argv[1:]))

    parser = argparse.ArgumentParser(prog="python -m batch.import_history", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", help="my_spotify_data.zip or the extracted folder")
    parser.add_argument("--min-plays", type=int, default=1, help="only tracks with at least N plays of >= 30s")
    parser.add_argument("--limit", type=int, help="only the N most-played tracks")
    parser.add_argument("--since", type=int, default=0, metavar="YYYY", help="only plays from this year on")
    parser.add_argument("--concurrency", type=int, default=1, help="parallel requests to the analyzer")
    parser.add_argument("--retry-failed", action="store_true", help="also retry tracks that failed before")
    parser.add_argument("--dry-run", action="store_true", help="print stats and exit")
    parser.add_argument("--db", default="results.db")
    parser.add_argument("--url", default=DEFAULT_URL)
    args = parser.parse_args(argv)
    args.concurrency = max(1, args.concurrency)

    try:
        return run_import(args)
    except (FileNotFoundError, ValueError) as e:
        print(f"[import] {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
