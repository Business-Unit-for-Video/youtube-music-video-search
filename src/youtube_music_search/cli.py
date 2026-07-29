from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

FIELDS = [
    "video_id", "url", "title", "channel", "channel_id", "duration",
    "upload_date", "availability", "live_status", "view_count",
    "matched_queries", "discovered_at",
]


def load_config(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or not config.get("queries"):
        raise ValueError("config must contain a non-empty queries list")
    return config


def canonical_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def normalize_entry(entry: dict[str, Any], query: str, discovered_at: str) -> dict[str, Any] | None:
    video_id = str(entry.get("id") or "").strip()
    if len(video_id) != 11:
        return None
    return {
        "video_id": video_id,
        "url": canonical_url(video_id),
        "title": entry.get("title") or "",
        "channel": entry.get("channel") or entry.get("uploader") or "",
        "channel_id": entry.get("channel_id") or entry.get("uploader_id") or "",
        "duration": entry.get("duration"),
        "upload_date": entry.get("upload_date") or "",
        "availability": entry.get("availability") or "",
        "live_status": entry.get("live_status") or "",
        "view_count": entry.get("view_count"),
        "matched_queries": [query],
        "discovered_at": discovered_at,
    }


def merge(existing: dict[str, Any], incoming: dict[str, Any]) -> None:
    existing["matched_queries"] = sorted(set(existing["matched_queries"] + incoming["matched_queries"]))
    for key in FIELDS:
        if key != "matched_queries" and not existing.get(key) and incoming.get(key):
            existing[key] = incoming[key]


def search_query(query: str, limit: int | None, sleep_interval: float) -> list[dict[str, Any]]:
    search_target = f"ytsearch{limit}:{query}" if limit is not None else f"ytsearchall:{query}"
    command = [
        sys.executable, "-m", "yt_dlp", "--flat-playlist", "--dump-json",
        "--ignore-errors", "--no-warnings", "--sleep-requests", str(sleep_interval),
        search_target,
    ]
    process = subprocess.run(command, text=True, capture_output=True)
    entries = []
    for line in process.stdout.splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if process.returncode and not entries:
        raise RuntimeError(process.stderr.strip() or f"yt-dlp failed for query: {query}")
    return entries


def write_outputs(records: list[dict[str, Any]], output_dir: Path, manifest: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "videos.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    with (output_dir / "videos.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for record in records:
            row = dict(record)
            row["matched_queries"] = " | ".join(row["matched_queries"])
            writer.writerow(row)
    (output_dir / "urls.txt").write_text("".join(record["url"] + "\n" for record in records), encoding="utf-8")
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(config: dict[str, Any], limit_override: int | None = None, search_all: bool = False) -> dict[str, Any]:
    queries = [str(query).strip() for query in config["queries"] if str(query).strip()]
    configured_limit = config.get("max_results_per_query")
    limit = None if search_all else (limit_override or (int(configured_limit) if configured_limit else None))
    sleep_interval = float(config.get("sleep_interval", 1.0))
    discovered_at = datetime.now(timezone.utc).isoformat()
    records: dict[str, dict[str, Any]] = {}
    query_counts: dict[str, int] = {}
    failures: dict[str, str] = {}
    for query in queries:
        print(f"Searching: {query}", flush=True)
        try:
            entries = search_query(query, limit, sleep_interval)
            query_counts[query] = len(entries)
            for entry in entries:
                record = normalize_entry(entry, query, discovered_at)
                if record is None:
                    continue
                if record["video_id"] in records:
                    merge(records[record["video_id"]], record)
                else:
                    records[record["video_id"]] = record
        except Exception as exc:
            failures[query] = str(exc)
            print(f"Search failed: {query}: {exc}", file=sys.stderr, flush=True)
    ordered = sorted(records.values(), key=lambda item: (item["title"].casefold(), item["video_id"]))
    config_hash = hashlib.sha256(yaml.safe_dump(config, allow_unicode=True, sort_keys=True).encode()).hexdigest()
    manifest = {
        "subject": config.get("subject", ""),
        "generated_at": discovered_at,
        "query_count": len(queries),
        "successful_query_count": len(query_counts),
        "failed_query_count": len(failures),
        "unique_video_count": len(ordered),
        "max_results_per_query": limit if limit is not None else "all_available",
        "query_result_counts": query_counts,
        "query_failures": failures,
        "config_sha256": config_hash,
        "scope_note": "Publicly discoverable YouTube results at collection time; deleted, private, region-restricted, unlisted, or search-suppressed videos may be absent.",
    }
    write_outputs(ordered, Path(config.get("output_dir", "output")), manifest)
    if not ordered:
        raise RuntimeError("no video URLs were discovered")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a deduplicated YouTube music-video URL inventory.")
    parser.add_argument("--config", type=Path, default=Path("config/searches.yaml"))
    parser.add_argument("--limit", type=int, help="Override max results per query")
    parser.add_argument("--all", action="store_true", help="Request all search results exposed by YouTube/yt-dlp")
    args = parser.parse_args()
    if args.all and args.limit is not None:
        parser.error("--all and --limit cannot be used together")
    manifest = run(load_config(args.config), args.limit, args.all)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
