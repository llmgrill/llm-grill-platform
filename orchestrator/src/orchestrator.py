import asyncio
from datetime import datetime, timedelta, timezone

from loguru import logger

from src.config import settings
from src.infra.terraform import (
    OutOfStockError,
    ScalewayAuthError,
    ScalewayQuotaError,
    TerraformError,
    destroy_node,
    provision_node,
)
from src.repositories.node_repository import NodeRepository
from src.repositories.run_repository import RunRepository

# Cap concurrent Terraform provisions to avoid Scaleway API spam and runaway costs.
_provision_semaphore = asyncio.Semaphore(3)


async def _fail(run_id, reason: str) -> None:
    await NodeRepository.set_down_by_run(run_id)
    await RunRepository.set_failed(run_id, datetime.now(timezone.utc), reason)


async def handle_queued_run(run_id, gpu_type_required) -> None:
    async with _provision_semaphore:
        await NodeRepository.create_provisioning(run_id, gpu_type_required)
        run = await RunRepository.get(run_id)
        if run is None:
            logger.warning("run {} disappeared before provisioning", run_id)
            await NodeRepository.set_down_by_run(run_id)
            return
        try:
            instance_id, public_ip = await provision_node(run)
        except (OutOfStockError, ScalewayQuotaError) as exc:
            reason = (
                "out of stock" if isinstance(exc, OutOfStockError) else "quota exceeded"
            )
            attempt = await RunRepository.requeue_for_retry(
                run_id, settings.provision_max_attempts
            )
            await NodeRepository.set_down_by_run(run_id)
            if attempt is None:
                logger.warning(
                    "run {} giving up after {} provision attempts ({})",
                    run_id,
                    settings.provision_max_attempts,
                    reason,
                )
                await RunRepository.set_failed(
                    run_id,
                    datetime.now(timezone.utc),
                    f"{reason} after {settings.provision_max_attempts} attempts",
                )
            else:
                logger.warning(
                    "run {} {}, re-queued (attempt {}/{})",
                    run_id,
                    reason,
                    attempt,
                    settings.provision_max_attempts,
                )
            return
        except ScalewayAuthError as exc:
            logger.warning("run {} provision failed: scaleway auth error", run_id)
            await _fail(run_id, f"scaleway auth: {exc}")
            return
        except TerraformError as exc:
            logger.warning("run {} provision failed: terraform error: {}", run_id, exc)
            await _fail(run_id, f"terraform: {exc}")
            return
        except Exception as exc:
            logger.exception("unexpected provision failure for run {}", run_id)
            await _fail(run_id, str(exc))
            return

        await NodeRepository.set_busy(run_id, instance_id, public_ip)
        await RunRepository.set_running(run_id, datetime.now(timezone.utc))
        logger.info("run {} running on node {} ({})", run_id, instance_id, public_ip)


async def release_node(run_id) -> None:
    try:
        await destroy_node(run_id)
    except Exception:
        logger.exception("failed to destroy node for run {}", run_id)
    await NodeRepository.set_down_by_run(run_id)


async def recover_leaked_nodes() -> None:
    """Destroy nodes left busy after a crash or restart."""
    leaked = await NodeRepository.get_leaked()
    if not leaked:
        return
    logger.warning("recovering {} leaked node(s) from previous run", len(leaked))
    for run_id in leaked:
        asyncio.create_task(release_node(run_id))


async def _abort_stuck_running(run_id) -> None:
    logger.warning(
        "run {} stuck in running for > {} min — force destroy",
        run_id,
        settings.run_running_timeout_minutes,
    )
    await release_node(run_id)
    await RunRepository.set_failed(
        run_id,
        datetime.now(timezone.utc),
        f"timeout: no /complete after {settings.run_running_timeout_minutes} min",
    )


async def reap_stuck_running() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(
        minutes=settings.run_running_timeout_minutes
    )
    stuck = await RunRepository.claim_running_timed_out(cutoff)
    for run_id in stuck:
        asyncio.create_task(_abort_stuck_running(run_id))


async def poll_once() -> None:
    claimed = await RunRepository.claim_queued()
    for run_id, gpu_type_required in claimed:
        asyncio.create_task(handle_queued_run(run_id, gpu_type_required))
    await reap_stuck_running()


async def polling_loop() -> None:
    await recover_leaked_nodes()
    while True:
        try:
            await poll_once()
        except Exception:
            logger.exception("orchestrator poll error")
        await asyncio.sleep(settings.poll_interval_seconds)
