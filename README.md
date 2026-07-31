# YouTube Music Video Search

Builds a deduplicated, auditable inventory of publicly discoverable YouTube video links for a configured music subject. The default configuration searches for 周杰伦 / Jay Chou videos through multiple Chinese and English query variants.

This repository collects metadata and links only. It does not download, copy, upload, or redistribute media, and a discovered link does not establish permission to reuse its content.

## Outputs

- `output/videos.csv`: primary publisher input, one selected 12-column video row per extracted Jay Chou song
- `output/videos.jsonl`: machine-readable primary one-video-per-song inventory
- `output/urls.txt`: one selected canonical watch URL per song
- `output/candidates.csv` / `output/candidates.jsonl` / `output/candidate_urls.txt`: complete deduplicated search candidates retained for audit, not publisher input
- `output/manifest.json`: run time, candidate count, selected-song count, query failures, and configuration hash
- `output/songs.csv`: selection audit with extracted song name, score, and reason
- `output/songs.jsonl`: machine-readable selection audit
- `output/song_urls.txt`: one selected URL per extracted song

“Complete” means the broadest reproducible inventory produced by the configured searches at collection time. YouTube may omit unlisted, private, deleted, region-restricted, or search-suppressed videos.

## Run

```bash
python -m pip install -e '.[test]'
pytest -q
youtube-music-search --config config/searches.yaml
```

Edit `config/searches.yaml` to change the subject or query set. GitHub Actions runs weekly and can also be dispatched manually. Its default `all` mode asks yt-dlp for every result YouTube exposes for each configured query; enter a positive integer for a faster bounded run.

## Data behavior

Results are first keyed by the 11-character YouTube video ID, canonicalized to `https://www.youtube.com/watch?v=<id>`, and merged when multiple queries find the same video. The full candidate set is retained in `output/candidates.*` for audit. `output/videos.csv` is intentionally narrower: it contains one selected video per extracted Jay Chou song so downstream publishers do not process thousands of search hits.

The song-level output excludes obvious compilations, albums, concerts, trailers, interviews, behind-the-scenes clips, reactions, covers, and other non-single-song titles. For each extracted song name it retains one candidate, ranking official Jay Chou/JVR channels first, then official MV or lyric-video markers, quality markers such as 4K/1080p, plausible song duration, and view count. This is a metadata-based selection: the collector does not download or measure audio, so it cannot prove which upload has the best codec, mastering, or tonal quality.
