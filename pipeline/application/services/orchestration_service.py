"""Main pipeline loop. Provisions per-model infra, runs backends concurrently,
writes JSONL results and a summary classified per ADR 001e."""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from dataclasses import dataclass
from typing import Any

from pipeline.application.domain.types import (
    BackendOutcome,
    ModelRunResult,
)
from pipeline.application.ports.infrastructure_port import (
    BenchmarkRunnerPort,
    InfrastructurePort,
    ProvisionedMachine,
)
from pipeline.application.ports.results_repository_port import ResultsRepositoryPort
from pipeline.application.services.discovery_service import DiscoveryResult

logger = logging.getLogger(__name__)


@dataclass
class OrchestrationConfig:
    per_backend_timeout_s: float
    date: str
    run_id: str


class OrchestrationService:
    def __init__(
        self,
        infrastructure: InfrastructurePort,
        runner: BenchmarkRunnerPort,
        results: ResultsRepositoryPort,
    ) -> None:
        self._infra = infrastructure
        self._runner = runner
        self._results = results

    async def run(
        self,
        plan: list[DiscoveryResult],
        config: OrchestrationConfig,
    ) -> list[ModelRunResult]:
        outcomes: list[ModelRunResult] = []
        for item in plan:
            outcomes.append(await self._run_model(item, config))
        self._write_summary(outcomes, config)
        return outcomes

    async def _run_model(
        self,
        item: DiscoveryResult,
        config: OrchestrationConfig,
    ) -> ModelRunResult:
        model_id = item.model.model_id
        slug = item.model.slug
        backends = item.pending_backends
        try:
            machines = self._infra.provision(model_id, list(backends), config.run_id)
        except Exception as exc:
            logger.exception("infra_failed for %s", model_id)
            return ModelRunResult(
                model_id=model_id, status="infra_failed", error=str(exc)
            )

        destroy_failed = False
        try:
            coros = [
                self._run_backend(m, model_id, slug, config)
                for m in machines
                if m.backend in backends
            ]
            raw = await asyncio.gather(*coros, return_exceptions=True)
            outcomes: list[BackendOutcome] = []
            for m, res in zip([m for m in machines if m.backend in backends], raw):
                if isinstance(res, Exception):
                    outcomes.append(
                        BackendOutcome(backend=m.backend, success=False, error=str(res))
                    )
                else:
                    outcomes.append(BackendOutcome(backend=m.backend, success=True))
        except Exception as exc:
            logger.exception("unknown_error for %s", model_id)
            try:
                self._infra.destroy(model_id, config.run_id)
            except Exception:
                destroy_failed = True
            status = "destroy_failed" if destroy_failed else "unknown_error"
            return ModelRunResult(model_id=model_id, status=status, error=str(exc))
        finally:
            try:
                self._infra.destroy(model_id, config.run_id)
            except Exception as exc:
                logger.exception("destroy_failed for %s", model_id)
                destroy_failed = True
                destroy_error = str(exc)

        if destroy_failed:
            return ModelRunResult(
                model_id=model_id,
                status="destroy_failed",
                backends=outcomes,
                error=locals().get("destroy_error"),
            )
        succeeded = sum(1 for o in outcomes if o.success)
        if succeeded == len(outcomes):
            status = "success"
        elif succeeded == 0:
            status = "unknown_error"
        else:
            status = "partial"
        return ModelRunResult(model_id=model_id, status=status, backends=outcomes)

    async def _run_backend(
        self,
        machine: ProvisionedMachine,
        model_id: str,
        slug: str,
        config: OrchestrationConfig,
    ) -> None:
        rows = await asyncio.wait_for(
            self._runner.run(machine, model_id, config.run_id),
            timeout=config.per_backend_timeout_s,
        )
        self._results.write_jsonl(config.date, slug, machine.backend, rows)

    def _write_summary(
        self,
        outcomes: list[ModelRunResult],
        config: OrchestrationConfig,
    ) -> None:
        counts: Counter[str] = Counter(o.status for o in outcomes)
        summary: dict[str, Any] = {
            "run_id": config.run_id,
            "date": config.date,
            "counts": {
                "success": counts.get("success", 0),
                "partial": counts.get("partial", 0),
                "infra_failed": counts.get("infra_failed", 0),
                "unknown_error": counts.get("unknown_error", 0),
                "destroy_failed": counts.get("destroy_failed", 0),
            },
            "models": [
                {
                    "model": o.model_id,
                    "status": o.status,
                    "error": o.error,
                    "backends": [
                        {"backend": b.backend, "success": b.success, "error": b.error}
                        for b in o.backends
                    ],
                }
                for o in outcomes
            ],
        }
        self._results.write_summary(summary)


def compute_run_id(date_iso: str, git_sha: str) -> str:
    return f"{date_iso}-{git_sha[:7]}"
