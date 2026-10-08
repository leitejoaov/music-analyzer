"""Constants and helpers with no heavy dependencies, so they can be tested without Essentia."""

# Each mood head is a binary classifier. The value is the index of the class we report,
# taken from the "classes" list in the model's .json metadata on essentia.upf.edu
# (e.g. mood_happy is ["happy", "non_happy"], mood_sad is ["non_sad", "sad"]).
MOOD_HEADS = {
    "mood_happy": 0,
    "mood_sad": 1,
    "mood_aggressive": 0,
    "mood_relaxed": 1,
    "mood_party": 1,
    "voice_instrumental": 0,  # ["instrumental", "voice"] — reported as 1 = instrumental
    "mood_acoustic": 0,
    "danceability": 0,
}

_DOWNLOAD_ERROR_PATTERNS = [
    ("age_restricted", ("confirm your age", "age-restricted", "age restricted")),
    ("forbidden", ("http error 403",)),
    (
        "network",
        (
            "failed to resolve",
            "temporary failure in name resolution",
            "name or service not known",
            "unable to download api page",
            "network is unreachable",
            "connection refused",
            "connection reset",
            "timed out",
        ),
    ),
    ("not_found", ("no results", "video unavailable", "not found")),
]


def classify_download_error(exc: Exception) -> str:
    """Map a yt-dlp failure to one of the audio_error categories of the API."""
    if isinstance(exc, FileNotFoundError):
        return "not_found"
    message = str(exc).lower()
    for category, patterns in _DOWNLOAD_ERROR_PATTERNS:
        if any(p in message for p in patterns):
            return category
    return "download_failed"
