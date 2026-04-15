"""Discovery orchestration: filters candidates and drops already-benchmarked pairs."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass

from pipeline.application.domain.types import Backend, ModelCandidate
from pipeline.application.ports.model_discovery_port import ModelDiscoveryPort
from pipeline.application.ports.results_repository_port import ResultsRepositoryPort


@dataclass
class DiscoveryFiltersConfig:
    task: str
    sort: str
    max_size_gb: float
    limit: int
    include_patterns: list[str]
    exclude_patterns: list[str]
    exclude_models: list[str]


@dataclass
class DiscoveryResult:
    model: ModelCandidate
    pending_backends: list[Backend]


class DiscoveryService:
    """Given filters and the repository, produce the list of (model, backends) to run."""

    def __init__(
        self,
        discovery: ModelDiscoveryPort,
        results: ResultsRepositoryPort,
    ) -> None:
        self._discovery = discovery
        self._results = results

    def plan(
        self,
        filters: DiscoveryFiltersConfig,
        configured_backends: list[Backend],
        date: str,
    ) -> list[DiscoveryResult]:
        candidates = self._discovery.discover(filters)
        plan: list[DiscoveryResult] = []
        for c in candidates:
            if not self._match(c, filters):
                continue
            backends = c.eligible_backends(configured_backends)
            pending = [
                b for b in backends if not self._results.has_result(date, c.slug, b)
            ]
            if pending:
                plan.append(DiscoveryResult(model=c, pending_backends=pending))
        return plan

    @staticmethod
    def _match(candidate: ModelCandidate, filters: DiscoveryFiltersConfig) -> bool:
        if candidate.model_id in filters.exclude_models:
            return False
        if candidate.size_gb > filters.max_size_gb:
            return False
        name = candidate.model_id.lower()
        if filters.include_patterns and not any(
            fnmatch.fnmatch(name, p.lower()) for p in filters.include_patterns
        ):
            return False
        if any(fnmatch.fnmatch(name, p.lower()) for p in filters.exclude_patterns):
            return False
        return True
