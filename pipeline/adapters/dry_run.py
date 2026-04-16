"""Stub adapters used by --dry-run: no provisioning, reads from fixtures."""

import json
from pathlib import Path

from pipeline.application.domain.types import ModelCandidate
from pipeline.application.ports.infrastructure_port import ProvisionedMachine


class FixtureDiscovery:
    """Surfaces the fixture directory as a model catalog."""

    def __init__(self, fixtures_root: Path) -> None:
        self._root = fixtures_root

    def discover(self, filters: object) -> list[ModelCandidate]:
        if not self._root.exists():
            return []
        seen: dict[str, ModelCandidate] = {}
        for date_dir in sorted(self._root.iterdir()):
            for slug_dir in sorted(date_dir.iterdir()):
                c = ModelCandidate(
                    model_id=slug_dir.name.replace("--", "/"),
                    size_gb=0.0,
                    has_gguf=(slug_dir / "llamacpp.jsonl").exists(),
                )
                seen[c.model_id] = c
        return list(seen.values())


class NoopInfrastructure:
    def provision(
        self, model_id: str, backends: list[str], run_id: str
    ) -> list[ProvisionedMachine]:
        return [
            ProvisionedMachine(backend=b, host="dry-run", instance_id="dry-run")
            for b in backends
        ]

    def destroy(self, model_id: str, run_id: str) -> None:
        pass


class FixtureRunner:
    def __init__(self, fixtures_root: Path, date: str) -> None:
        self._root = fixtures_root
        self._date = date

    async def run(
        self, machine: ProvisionedMachine, model_id: str, run_id: str
    ) -> list[dict]:
        path = (
            self._root
            / self._date
            / model_id.replace("/", "--")
            / f"{machine.backend}.jsonl"
        )
        if not path.exists():
            raise FileNotFoundError(path)
        with path.open("r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]


class LiveRunner:  # pragma: no cover
    async def run(
        self, machine: ProvisionedMachine, model_id: str, run_id: str
    ) -> list[dict]:
        raise NotImplementedError(
            "Live benchmark runner is provisioned by infra and not part of this module."
        )
