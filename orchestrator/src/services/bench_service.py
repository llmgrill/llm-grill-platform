import asyncio
import json
from typing import Literal

import yaml
from fastapi import HTTPException, status
from huggingface_hub import HfApi
from huggingface_hub.utils import RepositoryNotFoundError
from pydantic import BaseModel, field_validator

from src.catalog import build_models_catalog, build_scenarios_catalog
from src.config import settings
from src.models import ACTIVE_RUN_STATUSES, Engine
from src.repositories.run_repository import RunRepository
from src.schemas import RunCreate
from src.services.run_service import RunService
from src.storage import (
    head_latest_meta,
    upload_models_catalog,
    upload_scenarios_catalog,
)

_hf = HfApi()


class ModelEntry(BaseModel):
    model: str
    engine: Literal["vllm", "llamacpp"]
    size_b: int
    scenario: str = "scenarios/ramp.yaml"
    gguf_file: str | None = None

    @field_validator("gguf_file")
    @classmethod
    def gguf_required_for_llamacpp(cls, v: str | None, info) -> str | None:
        if info.data.get("engine") == "llamacpp" and not v:
            raise ValueError("gguf_file is required when engine is llamacpp")
        return v


def _load_models() -> list[ModelEntry]:
    with open(settings.models_file) as f:
        raw = yaml.safe_load(f)["models"]
    return [ModelEntry.model_validate(entry) for entry in raw]


async def _check_hf_exists(model_id: str) -> None:
    try:
        await asyncio.to_thread(
            _hf.model_info, model_id, token=settings.hf_token or None
        )
    except RepositoryNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Model not found on HuggingFace: {model_id}",
        )


async def _publish_catalogs(entries: list[ModelEntry]) -> None:
    """Publish derived models.json + scenarios.json for the static frontend.

    Derived from the full model list (ignores any `model_filter`) so the
    catalogs always describe every benchmarked model, not just the subset
    submitted this call.
    """
    await upload_models_catalog(json.dumps(build_models_catalog(entries)))
    await upload_scenarios_catalog(
        json.dumps(build_scenarios_catalog(settings.scenarios_root))
    )


async def submit(force: bool = False, model_filter: str | None = None) -> dict:
    entries = _load_models()
    await _publish_catalogs(entries)

    if model_filter:
        entries = [e for e in entries if model_filter.lower() in e.model.lower()]
        if not entries:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No model matching '{model_filter}' in models.yaml",
            )

    submitted: list[str] = []
    skipped: list[str] = []

    for entry in entries:
        label = f"{entry.model} [{entry.engine}]"

        if not force and await head_latest_meta(entry.model, Engine(entry.engine)):
            skipped.append(label)
            continue

        if await RunRepository.has_active_run(entry.model, entry.engine):
            skipped.append(f"{label} (already active)")
            continue

        await _check_hf_exists(entry.model)

        run = await RunService.create(
            RunCreate(
                model=entry.model,
                model_size_b=entry.size_b,
                engine=Engine(entry.engine),
                scenario_path=entry.scenario,
                gguf_file=entry.gguf_file,
            )
        )
        submitted.append(str(run.id))

    return {"submitted": submitted, "skipped": skipped}


async def bench_status() -> dict:
    counts = await RunRepository.count_by_status()
    active = sum(counts[s.value] for s in ACTIVE_RUN_STATUSES)
    return {"active": active, "counts": counts}
