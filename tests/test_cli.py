import subprocess

from youtube_music_search.cli import canonical_url, merge, normalize_entry, search_query


def test_normalize_entry_builds_canonical_url():
    record = normalize_entry({"id": "dQw4w9WgXcQ", "title": "Song", "channel": "Artist"}, "artist mv", "now")
    assert record is not None
    assert record["url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert record["matched_queries"] == ["artist mv"]


def test_invalid_video_id_is_rejected():
    assert normalize_entry({"id": "short"}, "query", "now") is None


def test_merge_deduplicates_queries_and_fills_metadata():
    first = normalize_entry({"id": "dQw4w9WgXcQ", "title": "Song"}, "q1", "now")
    second = normalize_entry({"id": "dQw4w9WgXcQ", "title": "Song", "channel": "Artist"}, "q2", "now")
    assert first and second
    merge(first, second)
    assert first["matched_queries"] == ["q1", "q2"]
    assert first["channel"] == "Artist"


def test_search_query_supports_all_available_results(monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout='{"id":"dQw4w9WgXcQ"}\n', stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    entries = search_query("artist mv", None, 1.0)
    assert captured["command"][-1] == "ytsearchall:artist mv"
    assert entries == [{"id": "dQw4w9WgXcQ"}]
