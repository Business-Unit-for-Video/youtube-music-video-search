from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

FIELDS = [
    "video_id", "url", "title", "channel", "channel_id", "duration",
    "upload_date", "availability", "live_status", "view_count",
    "matched_queries", "discovered_at",
]
SONG_FIELDS = [
    "song_name", "url", "title", "channel", "duration", "view_count",
    "selection_score", "selection_reason", "video_id",
]

COMPILATION_TERMS = re.compile(
    r"合集|串烧|歌单|精选|full album|top \d+|best songs|concert|演唱会|live|现场|"
    r"trailer|预告|花絮|making of|behind|special edition|interview|记者会|press conference|"
    r"周遊記|周游记|demo|广告|廣告|片段|reaction|翻唱|cover|教学|解析|"
    r"pre[- ]?order|teaser|release|album|shorts|intro|dvd|台北站|香港站|"
    r"全亚洲发片|全亞洲發片|簽唱會|签唱会|開箱|开箱|拍攝|拍摄|預購|预购|"
    r"發行|发行|宣傳|宣传|活動|活动|記錄|记录|花絮|預告|预告",
    re.IGNORECASE,
)
OFFICIAL_CHANNEL_TERMS = re.compile(r"周杰倫 Jay Chou$|^Jay Chou$|JVR Music Official", re.IGNORECASE)
LYRIC_CHANNEL_TERMS = re.compile(r"杰威爾歌詞MV|JVR Lyric", re.IGNORECASE)
QUALITY_TERMS = re.compile(r"4K|2160p|1080p|高清|高畫質|official music video|official mv", re.IGNORECASE)


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


def _canonical_song_name(name: str) -> str:
    name = re.split(r"\s*(?:feat\.?|ft\.?|with|特别演出|特別演出)\s*", name, maxsplit=1, flags=re.IGNORECASE)[0]
    chinese = re.findall(r"[\u3400-\u9fff]+", name)
    if chinese:
        return "".join(chinese)
    return re.sub(r"\s+", " ", name).strip(" -")


def _song_from_title(title: str) -> str | None:
    """Extract a canonical title only from an explicit official/JVR single-song title."""
    if not title or COMPILATION_TERMS.search(title):
        return None
    bracketed = re.findall(r"【([^】]+)】", title)
    if bracketed:
        name = re.sub(r"^周杰倫\s*", "", bracketed[-1], flags=re.IGNORECASE).strip()
        name = re.sub(r"^\s*\d{1,2}[.、\s-]+", "", name)
        name = re.split(r"\s+-\s+|\s+Official|\s+Lyric", name, maxsplit=1, flags=re.IGNORECASE)[0]
        name = _canonical_song_name(name.strip(" []()（）"))
        return name or None
    match = re.search(r"(?:Jay Chou|周杰伦|周杰倫)\s*[-–—:]\s*(.+?)(?:\s*\[|\s+(?:Official|Lyric|MV)\b|$)", title, re.IGNORECASE)
    if match and re.search(r"(?:official|lyric|\bmv\b)", title, re.IGNORECASE):
        name = _canonical_song_name(match.group(1).strip(" []()（）"))
        return name or None
    return None


def classify_song_candidate(record: dict[str, Any]) -> dict[str, Any] | None:
    """Score an explicit single-song video from trusted channels; never downloads media."""
    title = str(record.get("title") or "")
    channel = str(record.get("channel") or "")
    is_official = bool(OFFICIAL_CHANNEL_TERMS.search(channel))
    is_lyric = bool(LYRIC_CHANNEL_TERMS.search(channel))
    performer_prefix = title.split("【", 1)[0]
    title_mentions_jay = bool(re.search(
        r"Jay\s*Chou|周杰伦|周杰倫|JAY\s*CHOU", performer_prefix, re.IGNORECASE
    ))
    if not (is_official or is_lyric) or not title_mentions_jay:
        return None
    song_name = _song_from_title(title)
    if not song_name:
        return None
    duration = int(float(record.get("duration") or 0))
    if not 90 <= duration <= 600:
        return None
    views = int(record.get("view_count") or 0)
    score = 0
    reasons = []
    if is_official:
        score += 100
        reasons.append("official-channel")
    else:
        score += 85
        reasons.append("label-lyric-channel")
    if re.search(r"official music video|official mv", title, re.IGNORECASE):
        score += 35
        reasons.append("official-mv")
    if re.search(r"lyric", title, re.IGNORECASE):
        score += 25
        reasons.append("lyric-video")
    if QUALITY_TERMS.search(title):
        score += 12
        reasons.append("quality-marker")
    score += 10
    reasons.append("song-length")
    score += min(20, int((views or 0) ** 0.5 / 100))
    reasons.append("views-tiebreaker")
    return {
        "song_name": song_name,
        "url": record["url"],
        "title": title,
        "channel": channel,
        "duration": record.get("duration") or "",
        "view_count": record.get("view_count") or "",
        "selection_score": score,
        "selection_reason": ";".join(reasons),
        "video_id": record["video_id"],
    }


def select_one_video_per_song(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        candidate = classify_song_candidate(record)
        if candidate:
            candidates.setdefault(candidate["song_name"], []).append(candidate)
    selected = []
    for options in candidates.values():
        winner = max(options, key=lambda item: (item["selection_score"], int(item["view_count"] or 0)))
        selected.append(winner)
    return sorted(selected, key=lambda item: (item["song_name"].casefold(), item["video_id"]))


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


def _write_inventory(records: list[dict[str, Any]], output_dir: Path, stem: str) -> None:
    with (output_dir / f"{stem}.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    with (output_dir / f"{stem}.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        for record in records:
            row = dict(record)
            row["matched_queries"] = " | ".join(row["matched_queries"])
            writer.writerow(row)


def write_outputs(records: list[dict[str, Any]], output_dir: Path, manifest: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_inventory(records, output_dir, "candidates")
    (output_dir / "candidate_urls.txt").write_text(
        "".join(record["url"] + "\n" for record in records), encoding="utf-8"
    )
    songs = select_one_video_per_song(records)
    by_id = {record["video_id"]: record for record in records}
    selected_records = [by_id[song["video_id"]] for song in songs]
    _write_inventory(selected_records, output_dir, "videos")
    (output_dir / "urls.txt").write_text(
        "".join(record["url"] + "\n" for record in selected_records), encoding="utf-8"
    )
    with (output_dir / "songs.jsonl").open("w", encoding="utf-8") as handle:
        for song in songs:
            handle.write(json.dumps(song, ensure_ascii=False, sort_keys=True) + "\n")
    with (output_dir / "songs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SONG_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(songs)
    (output_dir / "song_urls.txt").write_text("".join(song["url"] + "\n" for song in songs), encoding="utf-8")
    manifest["candidate_video_count"] = len(records)
    manifest["unique_video_count"] = len(selected_records)
    manifest["single_song_count"] = len(songs)
    manifest["primary_output"] = "output/videos.csv contains one selected video per extracted Jay Chou song; output/candidates.csv retains raw search candidates for audit."
    manifest["song_selection"] = "One candidate per extracted song name; official channels, label lyric channel, quality markers, song-length duration, and views are metadata ranking signals. Audio was not downloaded or measured."
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
