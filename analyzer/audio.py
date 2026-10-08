"""Audio download (yt-dlp) and analysis (Essentia + MusiCNN mood models)."""
import glob
import logging
import math
import os
import uuid

import essentia.standard as es
import numpy as np
import yt_dlp

from .meta import MOOD_HEADS, classify_download_error

log = logging.getLogger(__name__)

MODELS_DIR = os.environ.get("MODELS_DIR", "/app/models")
MAX_DURATION_SECONDS = 600

EMBEDDING_MODEL = None
CLASSIFICATION_MODELS = {}


def load_models():
    global EMBEDDING_MODEL

    embedding_path = os.path.join(MODELS_DIR, "msd-musicnn-1.pb")
    if not os.path.exists(embedding_path):
        log.warning("MusiCNN embedding model not found, mood features disabled")
        return

    EMBEDDING_MODEL = es.TensorflowPredictMusiCNN(
        graphFilename=embedding_path, output="model/dense/BiasAdd"
    )
    for head in MOOD_HEADS:
        path = os.path.join(MODELS_DIR, f"{head}-msd-musicnn-1.pb")
        if os.path.exists(path):
            CLASSIFICATION_MODELS[head] = es.TensorflowPredict2D(
                graphFilename=path, output="model/Softmax"
            )
        else:
            log.warning("model not found: %s", path)


def download_audio(track: str, artist: str) -> str:
    """Download the first YouTube result for the track as mp3 and return its path."""
    output_path = f"/tmp/{uuid.uuid4()}"
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_path + ".%(ext)s",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "match_filter": yt_dlp.utils.match_filter_func(f"duration < {MAX_DURATION_SECONDS}"),
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],
        "socket_timeout": 60,
    }
    # Explicit ytsearch1: prefix, so a title like "re: stacks" is never read as a URL scheme
    query = f"ytsearch1:{track} {artist} official audio"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(query, download=True)
        matches = glob.glob(output_path + ".*")
        if not matches:
            raise FileNotFoundError("No results found on YouTube")
        mp3_path = output_path + ".mp3"
        return mp3_path if mp3_path in matches else matches[0]
    except Exception:
        _remove_files(output_path)
        raise


def analyze_file(file_path: str) -> dict:
    audio_44k = es.MonoLoader(filename=file_path, sampleRate=44100)()

    bpm, _, _, _, _ = es.RhythmExtractor2013(method="multifeature")(audio_44k)
    key, scale, _ = es.KeyExtractor()(audio_44k)

    loudness = es.Loudness()(audio_44k)
    loudness_db = 20 * math.log10(loudness + 1e-10)

    energy = es.Energy()(audio_44k)
    energy_normalized = min(1.0, energy / (len(audio_44k) * 0.1 + 1e-10))

    danceability_algo, _ = es.Danceability()(audio_44k)

    result = {
        "bpm": round(float(bpm), 1),
        "key": key,
        "mode": scale,
        "energy": round(float(energy_normalized), 2),
        "danceability": round(float(danceability_algo), 2),
        "loudness": round(float(loudness_db), 1),
    }

    if EMBEDDING_MODEL and CLASSIFICATION_MODELS:
        try:
            audio_16k = es.MonoLoader(filename=file_path, sampleRate=16000)()
            embeddings = EMBEDDING_MODEL(audio_16k)
            for head, model in CLASSIFICATION_MODELS.items():
                # predictions shape: (frames, 2)
                predictions = model(embeddings)
                score = float(np.mean(predictions[:, MOOD_HEADS[head]]))
                if head == "danceability":
                    # The model's danceability replaces the algorithmic one
                    result["danceability"] = round(score, 2)
                else:
                    result[head] = round(score, 3)
        except Exception as e:
            log.error("mood analysis failed (basic features still returned): %s", e)

    return result


def analyze_track(track: str, artist: str):
    """Return (audio_features, None) on success or (None, audio_error) on failure."""
    try:
        file_path = download_audio(track, artist)
    except Exception as e:
        log.error("download failed for %s - %s: %s", track, artist, e)
        return None, classify_download_error(e)

    try:
        return analyze_file(file_path), None
    except Exception as e:
        log.error("analysis failed for %s - %s: %s", track, artist, e)
        return None, "analysis_failed"
    finally:
        _remove_files(os.path.splitext(file_path)[0])


def _remove_files(prefix: str):
    for path in glob.glob(prefix + ".*"):
        try:
            os.remove(path)
        except OSError:
            pass


# Loaded at import time so each gunicorn worker gets its own copy of the models
load_models()
