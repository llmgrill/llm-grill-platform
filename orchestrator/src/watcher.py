import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

from huggingface_hub import list_models
from huggingface_hub.hf_api import ModelInfo
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models import Engine, Run, RunStatus
from src.routing import select_gpu

logger = logging.getLogger(__name__)

_SIZE_RE = re.compile(r"(\d+\.?\d*)[Bb]")
_SKIP_STATUSES = {RunStatus.queued, RunStatus.running, RunStatus.done}


async def watching_loop(session_factory) -> None:
    while True:
        try:
            await _scan_and_enqueue(session_factory)
        except Exception:
            logger.exception("watcher scan failed")
        await asyncio.sleep(settings.hf_watch_interval_seconds)


async def _scan_and_enqueue(session_factory) -> None:
    logger.info("watcher: scanning HuggingFace Hub")
    enqueued = 0
    since = datetime.now(timezone.utc) - timedelta(seconds=settings.hf_watch_interval_seconds)
    num_parameters = f"min:{settings.hf_min_size_b}B,max:{settings.hf_max_size_b}B"
    for model_info in list_models(
        pipeline_tag="text-generation",
        sort="created_at",
        num_parameters=num_parameters,
    ):
        if model_info.created_at and model_info.created_at < since:
            break
        if not _passes_filter(model_info):
            continue
        size_b = _extract_size_b(model_info)
        if size_b is None:
            continue
        async with session_factory() as session:
            if await _already_exists(session, model_info.id):
                continue
            engine = _detect_engine(model_info.id)
            run = Run(
                model=model_info.id,
                model_size_b=size_b,
                engine=engine,
                gpu_type_required=select_gpu(size_b),
                scenario_path=settings.hf_default_scenario,
            )
            session.add(run)
            await session.commit()
            enqueued += 1
            logger.info(
                "watcher: queued %s (%dB, %s)", model_info.id, size_b, engine.value
            )
    logger.info("watcher: scan done, %d new runs queued", enqueued)


def _extract_size_b(model_info: ModelInfo) -> int | None:
    match = _SIZE_RE.search(model_info.id)
    if match:
        return round(float(match.group(1)))
    return None


def _detect_engine(model_id: str) -> Engine:
    if "gguf" in model_id.lower():
        return Engine.llamacpp
    return Engine.vllm


def _passes_filter(model_info: ModelInfo) -> bool:
    """Accept a model if it comes from a watched org (or whitelist is empty = accept all)."""
    if not settings.hf_watched_orgs:
        return True
    org = model_info.id.split("/")[0]
    return org in settings.hf_watched_orgs


async def _already_exists(session: AsyncSession, model_id: str) -> bool:
    stmt = select(
        exists().where(Run.model == model_id).where(Run.status.in_(_SKIP_STATUSES))
    )
    result = await session.execute(stmt)
    return result.scalar()
