"""CLI entry point for the nightly benchmark pipeline."""

import asyncio
import datetime as dt
import subprocess
from pathlib import Path

import typer
import yaml
from loguru import logger

from pipeline.adapters.dry_run import (
    FixtureDiscovery,
    FixtureRunner,
    LiveRunner,
    NoopInfrastructure,
)
from pipeline.adapters.huggingface.model_discovery_adapter import (
    HuggingFaceModelDiscoveryAdapter,
)
from pipeline.adapters.storage.filesystem_results_repository import (
    FilesystemResultsRepository,
)
from pipeline.application.domain.config import PipelineConfig
from pipeline.application.services.aggregation_service import AggregationService
from pipeline.application.services.discovery_service import (
    DiscoveryResult,
    DiscoveryService,
)
from pipeline.application.services.orchestration_service import (
    OrchestrationConfig,
    OrchestrationService,
    compute_run_id,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
app = typer.Typer()


def _git_sha() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, stderr=subprocess.DEVNULL
            )
            .decode()
            .strip()
        )
    except Exception:
        return "0000000"


async def _amain(dry_run: bool) -> None:
    cfg = PipelineConfig.model_validate(
        yaml.safe_load((REPO_ROOT / "pipeline" / "config.yaml").read_text())
    )
    date = dt.date.today().isoformat()
    results_root = REPO_ROOT / "results"
    fixtures_root = results_root / "fixtures"
    repo = FilesystemResultsRepository(
        root=results_root,
        read_roots=[fixtures_root] if dry_run else None,
    )

    if dry_run:
        date = "2026-04-14"
        discovery_port = FixtureDiscovery(fixtures_root)
        infra = NoopInfrastructure()
        runner = FixtureRunner(fixtures_root, date)
    else:  # pragma: no cover
        from pipeline.adapters.terraform.infrastructure_adapter import (
            TerraformInfrastructureAdapter,
        )

        discovery_port = HuggingFaceModelDiscoveryAdapter()
        infra = TerraformInfrastructureAdapter(tf_dir=REPO_ROOT / "infra")
        runner = LiveRunner()

    plan = DiscoveryService(discovery_port, repo).plan(
        cfg.discovery, cfg.backends, date
    )
    if dry_run and not plan:
        plan = [
            DiscoveryResult(model=c, pending_backends=c.eligible_backends(cfg.backends))
            for c in FixtureDiscovery(fixtures_root).discover(cfg.discovery)
        ]

    plan = plan[: cfg.load.max_models_per_day]
    logger.info("plan: {} model(s) (limit {})", len(plan), cfg.load.max_models_per_day)

    run_id = compute_run_id(date, _git_sha())
    await OrchestrationService(infra, runner, repo).run(
        plan,
        OrchestrationConfig(
            per_backend_timeout_s=cfg.load.per_backend_timeout_s,
            date=date,
            run_id=run_id,
        ),
    )
    AggregationService(repo).aggregate()
    logger.info("done run_id={}", run_id)


@app.command()
def main(
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Use fixtures, no provisioning."
    ),
) -> None:
    asyncio.run(_amain(dry_run=dry_run))


if __name__ == "__main__":
    app()
