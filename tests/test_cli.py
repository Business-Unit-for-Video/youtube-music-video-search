import subprocess

from youtube_music_search.cli import (
    canonical_url,
    merge,
    normalize_entry,
    search_query,
    select_one_video_per_song,
    write_outputs,
)


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


def test_select_one_official_video_per_song():
    records = [
        normalize_entry({"id": "dQw4w9WgXcQ", "title": "Jay Chou 周杰伦【青花瓷】Official Music Video", "channel": "周杰倫 Jay Chou", "duration": 240, "view_count": 100}, "q", "now"),
        normalize_entry({"id": "9bZkp7q19f0", "title": "Jay Chou 周杰伦【青花瓷】Lyric Video [4K]", "channel": "杰威爾歌詞MV頻道JVR Lyric MV", "duration": 240, "view_count": 9999999}, "q", "now"),
    ]
    selected = select_one_video_per_song([record for record in records if record])
    assert len(selected) == 1
    assert selected[0]["song_name"] == "青花瓷"
    assert selected[0]["video_id"] == "dQw4w9WgXcQ"


def test_song_selection_merges_bilingual_title_variants():
    records = [
        normalize_entry({"id": "dQw4w9WgXcQ", "title": "周杰倫 Jay Chou【半獸人 Half-beast Human】Official MV", "channel": "周杰倫 Jay Chou", "duration": 248}, "q", "now"),
        normalize_entry({"id": "9bZkp7q19f0", "title": "周杰倫 Jay Chou【半獸人 Half beast Human】Official MV [4K]", "channel": "杰威爾歌詞MV頻道JVR Lyric MV", "duration": 248}, "q", "now"),
    ]
    selected = select_one_video_per_song([record for record in records if record])
    assert len(selected) == 1
    assert selected[0]["song_name"] == "半獸人"
    assert selected[0]["video_id"] == "dQw4w9WgXcQ"


def test_song_selection_rejects_noise_and_untrusted_channels():
    records = [
        normalize_entry({"id": "dQw4w9WgXcQ", "title": "周杰倫 Jay Chou【青花瓷】Official MV", "channel": "周杰倫 Jay Chou", "duration": 240}, "q", "now"),
        normalize_entry({"id": "9bZkp7q19f0", "title": "周杰倫 Jay Chou 前20名合集 Top 20 songs", "channel": "周杰倫 Jay Chou", "duration": 2400}, "q", "now"),
        normalize_entry({"id": "a1b2c3d4e5F", "title": "周杰倫 Jay Chou【青花瓷】翻唱", "channel": "Random Cover Channel", "duration": 240}, "q", "now"),
        normalize_entry({"id": "f1e2d3c4b5A", "title": "周杰倫 Jay Chou【青花瓷】MV花絮 Making of", "channel": "周杰倫 Jay Chou", "duration": 240}, "q", "now"),
    ]
    selected = select_one_video_per_song([record for record in records if record])
    assert [item["song_name"] for item in selected] == ["青花瓷"]
    assert selected[0]["video_id"] == "dQw4w9WgXcQ"


def test_song_selection_rejects_other_jvr_artists():
    records = [
        normalize_entry({"id": "dQw4w9WgXcQ", "title": "周杰倫 Jay Chou【青花瓷】Official MV", "channel": "周杰倫 Jay Chou", "duration": 240}, "q", "now"),
        normalize_entry({"id": "9bZkp7q19f0", "title": "浪花兄弟 The Drifters【你是我的OK繃】Official MV 周杰倫作曲", "channel": "杰威爾音樂 JVR Music Official", "duration": 286}, "q", "now"),
    ]
    selected = select_one_video_per_song([record for record in records if record])
    assert [item["song_name"] for item in selected] == ["青花瓷"]


def test_song_name_excludes_featured_artist():
    record = normalize_entry({"id": "dQw4w9WgXcQ", "title": "周杰倫 Jay Chou【傻笑 Smile (feat. 袁詠琳 Cindy)】Official MV", "channel": "周杰倫 Jay Chou", "duration": 240}, "q", "now")
    selected = select_one_video_per_song([record] if record else [])
    assert selected[0]["song_name"] == "傻笑"


def test_primary_video_output_is_one_row_per_song(tmp_path):
    records = [
        normalize_entry({"id": "dQw4w9WgXcQ", "title": "周杰倫 Jay Chou【青花瓷】Official MV", "channel": "周杰倫 Jay Chou", "duration": 240}, "q", "now"),
        normalize_entry({"id": "9bZkp7q19f0", "title": "Jay Chou 周杰倫【青花瓷】Lyric Video", "channel": "杰威爾歌詞MV頻道JVR Lyric MV", "duration": 240}, "q", "now"),
        normalize_entry({"id": "a1b2c3d4e5F", "title": "周杰倫 Jay Chou【七里香】Official MV", "channel": "周杰倫 Jay Chou", "duration": 250}, "q", "now"),
    ]
    manifest = {}
    write_outputs([record for record in records if record], tmp_path, manifest)
    assert len((tmp_path / "videos.csv").read_text().splitlines()) == 3
    assert len((tmp_path / "candidates.csv").read_text().splitlines()) == 4
    assert manifest["unique_video_count"] == 2
    assert manifest["candidate_video_count"] == 3
