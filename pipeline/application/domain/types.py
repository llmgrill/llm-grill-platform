"""Domain value objects for the pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Backend = Literal["vllm", "llamacpp"]
ModelStatus = Literal[
    "success", "partial", "infra_failed", "unknown_error", "destroy_failed"
]


@dataclass(frozen=True)
class ModelCandidate:
    """A model surfaced by discovery and eligible for benchmarking."""

    model_id: str  # HuggingFace ID, e.g. "meta-llama/Llama-3.1-8B-Instruct"
    size_gb: float
    has_gguf: bool

    @property
    def slug(self) -> str:
        return self.model_id.replace("/", "--")

    def eligible_backends(self, configured: list[Backend]) -> list[Backend]:
        out: list[Backend] = []
        for b in configured:
            if b == "llamacpp" and not self.has_gguf:
                continue
            out.append(b)
        return out


@dataclass
class BackendOutcome:
    backend: Backend
    success: bool
    error: str | None = None


@dataclass
class ModelRunResult:
    model_id: str
    status: ModelStatus
    backends: list[BackendOutcome] = field(default_factory=list)
    error: str | None = None
