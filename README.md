# YouTube Music Video Search

Builds a deduplicated, auditable inventory of publicly discoverable YouTube video links for a configured music subject. The default configuration searches for 周杰伦 / Jay Chou videos through multiple Chinese and English query variants.

This repository collects metadata and links only. It does not download, copy, upload, or redistribute media, and a discovered link does not establish permission to reuse its content.

## Outputs

- `output/urls.txt`: one canonical watch URL per line
- `output/videos.csv`: spreadsheet-friendly metadata and matched queries
- `output/videos.jsonl`: machine-readable records
- `output/manifest.json`: run time, query counts, failures, result total, and configuration hash

“Complete” means the broadest reproducible inventory produced by the configured searches at collection time. YouTube may omit unlisted, private, deleted, region-restricted, or search-suppressed videos.

## Run

```bash
python -m pip install -e '.[test]'
pytest -q
youtube-music-search --config config/searches.yaml
```

Edit `config/searches.yaml` to change the subject or query set. GitHub Actions runs weekly and can also be dispatched manually. Its default `all` mode asks yt-dlp for every result YouTube exposes for each configured query; enter a positive integer for a faster bounded run.

## Data behavior

Results are keyed by the 11-character YouTube video ID, canonicalized to `https://www.youtube.com/watch?v=<id>`, and merged when multiple queries find the same video. Each row retains all matching queries so discoveries can be audited and the search strategy can be improved.
