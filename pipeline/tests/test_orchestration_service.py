from __future__ import annotations

import asyncio


from pipeline.adapters.storage.filesystem_results_repository import (
    InMemoryResultsRepository,
)
from pipeline.application.domain.types import ModelCandidate
from pipeline.application.ports.infrastructure_port import ProvisionedMachine
from pipeline.application.services.discovery_service import DiscoveryResult
from pipeline.application.services.orchestration_service import (
    OrchestrationConfig,
    OrchestrationService,
    compute_run_id,
)


class _FakeInfra:
    def __init__(
        self, fail_provision: bool = False, fail_destroy: bool = False
    ) -> None:
        self.provisioned: list[tuple[str, list[str]]] = []
        self.destroyed: list[str] = []
        self._fail_provision = fail_provision
        self._fail_destroy = fail_destroy

    def provision(self, model_id, backends, run_id):
        if self._fail_provision:
            raise RuntimeError("terraform apply failed")
        self.provisioned.append((model_id, backends))
        return [
            ProvisionedMachine(backend=b, host=f"h-{b}", instance_id=f"i-{b}")
            for b in backends
        ]

    def destroy(self, model_id, run_id):
        if self._fail_destroy:
            raise RuntimeError("terraform destroy failed")
        self.destroyed.append(model_id)


class _FakeRunner:
    def __init__(self, failing_backends: set[str] | None = None) -> None:
        self._failing = failing_backends or set()

    async def run(self, machine, model_id, run_id):
        if machine.backend in self._failing:
            raise RuntimeError(f"backend {machine.backend} failed")
        return [
            {
                "scenario": "nightly",
                "server": machine.backend,
                "model": model_id,
                "success": True,
                "ttft_ms": 1.0,
            }
        ]


def _plan() -> list[DiscoveryResult]:
    c = ModelCandidate("org/Model-Instruct", 5.0, True)
    return [DiscoveryResult(model=c, pending_backends=["vllm", "llamacpp"])]


def test_run_given_all_backends_succeed_when_orchestrated_then_status_success():
    # Given
    repo = InMemoryResultsRepository()
    infra = _FakeInfra()
    service = OrchestrationService(infra, _FakeRunner(), repo)

    # When
    outcomes = asyncio.run(
        service.run(
            _plan(),
            OrchestrationConfig(
                per_backend_timeout_s=10, date="2026-04-14", run_id="rid"
            ),
        )
    )

    # Then
    assert outcomes[0].status == "success"
    assert infra.destroyed == ["org/Model-Instruct"]
    assert ("2026-04-14", "org--Model-Instruct", "vllm") in repo.runs
    assert repo.summary["counts"]["success"] == 1


def test_run_given_one_backend_fails_when_orchestrated_then_status_partial_and_destroy_called():
    # Given
    repo = InMemoryResultsRepository()
    infra = _FakeInfra()
    service = OrchestrationService(
        infra, _FakeRunner(failing_backends={"llamacpp"}), repo
    )

    # When
    outcomes = asyncio.run(
        service.run(
            _plan(),
            OrchestrationConfig(
                per_backend_timeout_s=10, date="2026-04-14", run_id="rid"
            ),
        )
    )

    # Then
    assert outcomes[0].status == "partial"
    assert infra.destroyed == ["org/Model-Instruct"]
    # successful backend data was written
    assert ("2026-04-14", "org--Model-Instruct", "vllm") in repo.runs
    assert ("2026-04-14", "org--Model-Instruct", "llamacpp") not in repo.runs
    assert repo.summary["counts"]["partial"] == 1


def test_run_given_provision_fails_when_orchestrated_then_status_infra_failed_and_no_destroy():
    # Given
    repo = InMemoryResultsRepository()
    infra = _FakeInfra(fail_provision=True)
    service = OrchestrationService(infra, _FakeRunner(), repo)

    # When
    outcomes = asyncio.run(
        service.run(
            _plan(),
            OrchestrationConfig(
                per_backend_timeout_s=10, date="2026-04-14", run_id="rid"
            ),
        )
    )

    # Then
    assert outcomes[0].status == "infra_failed"
    assert infra.destroyed == []
    assert repo.summary["counts"]["infra_failed"] == 1


def test_run_given_destroy_fails_when_orchestrated_then_status_destroy_failed():
    # Given
    repo = InMemoryResultsRepository()
    infra = _FakeInfra(fail_destroy=True)
    service = OrchestrationService(infra, _FakeRunner(), repo)

    # When
    outcomes = asyncio.run(
        service.run(
            _plan(),
            OrchestrationConfig(
                per_backend_timeout_s=10, date="2026-04-14", run_id="rid"
            ),
        )
    )

    # Then
    assert outcomes[0].status == "destroy_failed"
    assert repo.summary["counts"]["destroy_failed"] == 1


def test_compute_run_id_given_date_and_sha_then_formats_as_date_plus_short_sha():
    assert compute_run_id("2026-04-14", "abc1234deadbeef") == "2026-04-14-abc1234"
