"""
Dry-run the HuggingFace watcher — prints models that would be enqueued
without touching the database.

Usage:
    uv run python scripts/dry_run_watcher.py
    uv run python scripts/dry_run_watcher.py --days 30
    uv run python scripts/dry_run_watcher.py --days 7
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from huggingface_hub import list_models

from src.config import settings
from src.watcher import _detect_engine, _extract_size_b, _passes_filter


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=1, help="Time window in days")
    parser.add_argument("--min-size-b", type=int, default=settings.hf_min_size_b)
    parser.add_argument("--max-size-b", type=int, default=settings.hf_max_size_b)
    args = parser.parse_args()

    settings.hf_min_size_b = args.min_size_b
    settings.hf_max_size_b = args.max_size_b

    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    num_parameters = f"min:{args.min_size_b}B,max:{args.max_size_b}B"

    print(f"\n{'='*60}")
    print(f"  Watcher dry-run — window: {args.days}d | since: {since.date()}")
    print(f"  Size: [{args.min_size_b}B, {args.max_size_b}B]")
    print(f"  Watched orgs: {', '.join(settings.hf_watched_orgs) or '(all)'}")
    print(f"{'='*60}\n")

    total_seen = 0
    skipped_filter = 0
    skipped_size = 0
    would_enqueue = []
    filtered_out = []

    for model_info in list_models(
        pipeline_tag="text-generation",
        sort="created_at",
        num_parameters=num_parameters,
    ):
        if model_info.created_at and model_info.created_at < since:
            print(f"  [stop] too old: {model_info.id} ({model_info.created_at.date()})\n")
            break

        total_seen += 1

        if not _passes_filter(model_info):
            skipped_filter += 1
            filtered_out.append((model_info.id, model_info.downloads or 0))
            continue

        size_b = _extract_size_b(model_info)
        if size_b is None:
            skipped_size += 1
            continue

        engine = _detect_engine(model_info.id)
        would_enqueue.append((model_info.id, size_b, engine.value, model_info.downloads or 0))

    print(f"\n{'='*60}")
    print(f"  Seen: {total_seen} | would enqueue: {len(would_enqueue)} | skip filter: {skipped_filter} | skip size: {skipped_size}")
    print(f"{'='*60}")

    if would_enqueue:
        print(f"\n  Top 5 would-enqueue by downloads:")
        for model_id, size_b, engine, downloads in sorted(would_enqueue, key=lambda x: x[3], reverse=True)[:5]:
            print(f"    {model_id} | {size_b}B | {engine} | {downloads:,} dl")
    else:
        print(f"\n  No models to enqueue in this window — try --days 30")

    if filtered_out:
        print(f"\n  Top 5 filtered-out by downloads:")
        for model_id, downloads in sorted(filtered_out, key=lambda x: x[1], reverse=True)[:5]:
            print(f"    {model_id} | {downloads:,} dl")

    print()


if __name__ == "__main__":
    main()
