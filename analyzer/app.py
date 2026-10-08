"""HTTP API: one call per track returns audio features and lyrics."""
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, jsonify, request

from . import audio
from .lyrics import fetch_lyrics

app = Flask(__name__)


@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not data.get("track") or not data.get("artist"):
        return jsonify({"error": "Missing 'track' and 'artist' in request body"}), 400

    track, artist = str(data["track"]), str(data["artist"])

    # Audio and lyrics are independent: a blocked download still returns lyrics
    with ThreadPoolExecutor(max_workers=1) as pool:
        lyrics_future = pool.submit(_safe_fetch_lyrics, artist, track)
        audio_features, audio_error = audio.analyze_track(track, artist)
        lyrics = lyrics_future.result()

    if lyrics:
        lyrics_payload = {"found": True, "source": lyrics[1], "text": lyrics[0]}
    else:
        lyrics_payload = {"found": False, "source": None, "text": None}

    return jsonify(
        {
            "track": track,
            "artist": artist,
            "audio": audio_features,
            "audio_error": audio_error,
            "lyrics": lyrics_payload,
        }
    )


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "tf_models_loaded": len(audio.CLASSIFICATION_MODELS)})


def _safe_fetch_lyrics(artist: str, track: str):
    try:
        return fetch_lyrics(artist, track)
    except Exception as e:
        app.logger.error("lyrics lookup failed for %s - %s: %s", track, artist, e)
        return None


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
