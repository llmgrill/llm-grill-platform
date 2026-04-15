"""HuggingFace Hub discovery adapter."""

from __future__ import annotations

import logging
from typing import Any

from huggingface_hub import HfApi, ModelInfo

from pipeline.application.domain.types import ModelCandidate
from pipeline.application.ports.model_discovery_port import DiscoveryFilters

logger = logging.getLogger(__name__)


class HuggingFaceModelDiscoveryAdapter:
    """Wraps ``huggingface_hub.HfApi`` to surface candidate models.

    The ``hf_api`` parameter is injectable so tests can pass a fake without
    touching the network. Missing ``huggingface_hub`` at runtime degrades the
    adapter into an empty-list producer with a warning.
    """

    def __init__(self, hf_api: HfApi | None = None, token: str | None = None) -> None:
        if hf_api is None:
            try:  # pragma: no cover - exercised only when lib is installed
                hf_api = HfApi(token=token)
            except Exception as exc:  # pragma: no cover - exercised only on missing dep
                logger.warning("huggingface_hub not available: %s", exc)
                hf_api = None
        self._api = hf_api

    def discover(self, filters: DiscoveryFilters) -> list[ModelCandidate]:
        if self._api is None:
            return []
        raw = self._api.list_models(
            task=filters.task,
            sort=filters.sort,
            limit=filters.limit,
            full=True,
        )
        out: list[ModelCandidate] = []
        for m in raw:
            size_gb = _safetensors_size_gb(m)
            has_gguf = _has_gguf(m)
            out.append(
                ModelCandidate(
                    model_id=getattr(m, "id", getattr(m, "modelId", "")),
                    size_gb=size_gb,
                    has_gguf=has_gguf,
                )
            )
        return out


def _safetensors_size_gb(model: ModelInfo) -> float:
    siblings = getattr(model, "siblings", None) or []
    total = 0
    for s in siblings:
        name = getattr(s, "rfilename", "") or ""
        size = getattr(s, "size", 0) or 0
        if name.endswith(".safetensors"):
            total += size
    return total / (1024**3) if total else 0.0


def _has_gguf(model: ModelInfo) -> bool:
    siblings = getattr(model, "siblings", None) or []
    return any((getattr(s, "rfilename", "") or "").endswith(".gguf") for s in siblings)
