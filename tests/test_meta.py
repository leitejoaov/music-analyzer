from analyzer.meta import MOOD_HEADS, classify_download_error


def test_mood_heads_report_the_named_class():
    assert MOOD_HEADS == {
        "mood_happy": 0,
        "mood_sad": 1,
        "mood_aggressive": 0,
        "mood_relaxed": 1,
        "mood_party": 1,
        "voice_instrumental": 0,
        "mood_acoustic": 0,
        "danceability": 0,
    }


def test_classify_download_error():
    cases = {
        "ERROR: [youtube] abc: Sign in to confirm your age. Use --cookies": "age_restricted",
        "ERROR: unable to download video data: HTTP Error 403: Forbidden": "forbidden",
        "ERROR: Unable to download API page: HTTPSConnection(host='www.youtube.com', port=443): "
        "Failed to resolve 'www.youtube.com' ([Errno -3] Temporary failure in name resolution)": "network",
        "ERROR: [download] Got error: HTTPSConnectionPool(host='x.googlevideo.com'): Read timed out.": "network",
        "something yt-dlp never said before": "download_failed",
    }
    for message, expected in cases.items():
        assert classify_download_error(Exception(message)) == expected


def test_missing_file_is_not_found():
    assert classify_download_error(FileNotFoundError("No results found on YouTube")) == "not_found"
