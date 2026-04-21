"""
One-shot bootstrap: seed the DB with popular HuggingFace models.

Unlike the recurring watcher (24h window + org whitelist), this script does a
full historical scan and accepts models that pass either criterion:
  (org in whitelist) OR (downloads >= min_downloads)

Usage:
    uv run python scripts/bootstrap_models.py
    uv run python scripts/bootstrap_models.py --min-downloads 50000
    uv run python scripts/bootstrap_models.py --min-downloads 100000 --dry-run
    uv run python scripts/bootstrap_models.py --min-downloads 50000 --limit 200
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from huggingface_hub import list_models

from src.config import settings
from src.db import AsyncSessionLocal
from src.models import Run
from src.routing import select_gpu
from src.watcher import _already_exists, _detect_engine, _extract_size_b


def _passes_bootstrap_filter(model_info, min_downloads: int) -> bool:
    org = model_info.id.split("/")[0]
    in_whitelist = (not settings.hf_watched_orgs) or org in settings.hf_watched_orgs
    has_downloads = (model_info.downloads or 0) >= min_downloads
    return in_whitelist or has_downloads


async def run(min_downloads: int, dry_run: bool, limit: int | None) -> None:
    num_parameters = f"min:{settings.hf_min_size_b}B,max:{settings.hf_max_size_b}B"

    print(f"\n{'='*65}")
    print(f"  HuggingFace bootstrap — {'DRY RUN ' if dry_run else ''}seed DB")
    print(f"  Size: [{settings.hf_min_size_b}B, {settings.hf_max_size_b}B]")
    print(f"  Filter: org in whitelist OR downloads >= {min_downloads:,}")
    print(f"  Orgs: {', '.join(settings.hf_watched_orgs) or '(all)'}")
    if limit:
        print(f"  Limit: {limit} models max")
    print(f"{'='*65}\n")

    seen = 0
    skipped_filter = 0
    skipped_size = 0
    skipped_dedup = 0
    inserted = 0

    for model_info in list_models(
        pipeline_tag="text-generation",
        sort="downloads",
        num_parameters=num_parameters,
    ):
        if limit and seen >= limit:
            print(f"\n  [limit reached: {limit}]")
            break

        seen += 1

        if not _passes_bootstrap_filter(model_info, min_downloads):
            skipped_filter += 1
            continue

        size_b = _extract_size_b(model_info)
        if size_b is None:
            skipped_size += 1
            print(f"  [skip size?] {model_info.id}")
            continue

        async with AsyncSessionLocal() as session:
            if await _already_exists(session, model_info.id):
                skipped_dedup += 1
                continue

            engine = _detect_engine(model_info.id)
            tag = "[dry]" if dry_run else "[ OK]"
            print(
                f"  {tag} {model_info.id} | {size_b}B | {engine.value} | {model_info.downloads or 0:,} dl"
            )

            if not dry_run:
                run_obj = Run(
                    model=model_info.id,
                    model_size_b=size_b,
                    engine=engine,
                    gpu_type_required=select_gpu(size_b),
                    scenario_path=settings.hf_default_scenario,
                )
                session.add(run_obj)
                await session.commit()
            inserted += 1

    action = "would insert" if dry_run else "inserted"
    print(f"\n{'='*65}")
    print(f"  Seen: {seen} | {action}: {inserted} | skip filter: {skipped_filter} | skip size: {skipped_size} | skip dedup: {skipped_dedup}")
    print(f"{'='*65}\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-downloads", type=int, default=50_000)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    asyncio.run(run(args.min_downloads, args.dry_run, args.limit))


if __name__ == "__main__":
    main()
