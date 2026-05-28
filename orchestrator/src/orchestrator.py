import asyncio
from datetime import datetime, timedelta, timezone

from loguru import logger

from src.config import settings
from src.infra.terraform import (
    OutOfStockError,
    ScalewayAuthError,
    ScalewayQuotaError,
    ServerStartError,
    TerraformError,
    destroy_node,
    provision_node,
)
from src.repositories.node_repository import NodeRepository
from src.repositories.run_repository import RunRepository

# Cap concurrent Terraform provisions to avoid Scaleway API spam and runaway costs.
# The semaphore serializes the actual terraform work; `_in_flight_provisions`
# tracks every run we have committed to (claimed in DB or already inside the
# semaphore) so poll_once never over-claims, even before tasks have had a
# chance to acquire the semaphore.
_MAX_CONCURRENT_PROVISIONS = settings.max_concurrent_provisions
_provision_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_PROVISIONS)
_in_flight_provisions = 0


def _free_provision_slots() -> int:
    return max(0, _MAX_CONCURRENT_PROVISIONS - _in_flight_provisions)


async def _fail(run_id, reason: str) -> None:
    await NodeRepository.set_down_by_run(run_id)
    await RunRepository.set_failed(run_id, datetime.now(timezone.utc), reason)


async def _safe_destroy(run_id) -> None:
    """Best-effort teardown of half-provisioned infra; never raises.

    Used when a failure leaves a real Scaleway server behind (e.g. created but
    stopped), so a retry starts clean and a give-up doesn't leak a GPU + its
    volume/IP. Destroy failures are logged, not propagated.
    """
    try:
        await destroy_node(run_id)
    except Exception:
        logger.exception("cleanup destroy failed for run {}", run_id)


async def handle_queued_run(run_id, gpu_type_required) -> None:
    global _in_flight_provisions
    try:
        async with _provision_semaphore:
            try:
                await _provision_under_permit(run_id, gpu_type_required)
            except Exception as exc:
                # Last-resort guard: any unexpected error before/around
                # provision_node would otherwise leave the run pinned in
                # `provisioning` until the watchdog reaps it 30 min later.
                logger.exception("unhandled error in provisioning of run {}", run_id)
                await _fail(run_id, f"unhandled: {exc}")
    finally:
        _in_flight_provisions -= 1


async def _provision_under_permit(run_id, gpu_type_required) -> None:
    await NodeRepository.create_provisioning(run_id, gpu_type_required)
    run = await RunRepository.get(run_id)
    if run is None:
        logger.warning("run {} disappeared before provisioning", run_id)
        await NodeRepository.set_down_by_run(run_id)
        return
    try:
        instance_id, public_ip = await provision_node(run)
    except (OutOfStockError, ScalewayQuotaError, ServerStartError) as exc:
        if isinstance(exc, OutOfStockError):
            reason = "out of stock"
        elif isinstance(exc, ScalewayQuotaError):
            reason = "quota exceeded"
        else:
            reason = "server failed to start"
        # ServerStartError means a server resource was actually created (it's just
        # stopped) — tear it down so we don't keep a dead GPU + its volume/IP
        # billing across retries, and don't leak it on give-up. OutOfStock/Quota
        # never created anything, so skip the (costly) destroy for them.
        if isinstance(exc, ServerStartError):
            await _safe_destroy(run_id)
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


async def _recover_orphaned_provisioning_run(run_id) -> None:
    # Clean up any half-provisioned VM + workspace + node row, then either
    # requeue for another attempt or mark failed if max attempts reached.
    await release_node(run_id)
    attempt = await RunRepository.requeue_for_retry(
        run_id, settings.provision_max_attempts
    )
    if attempt is None:
        logger.warning(
            "orphaned provisioning run {} exceeded {} attempts — failing",
            run_id,
            settings.provision_max_attempts,
        )
        await RunRepository.set_failed(
            run_id,
            datetime.now(timezone.utc),
            "orphaned in provisioning after restart",
        )
    else:
        logger.info(
            "orphaned provisioning run {} re-queued (attempt {}/{})",
            run_id,
            attempt,
            settings.provision_max_attempts,
        )


async def recover_orphaned_provisioning() -> None:
    """Re-queue runs left in `provisioning` from a crash/restart.

    The terraform subprocess that owned them is gone, so they can't complete
    on their own. We tear down any half-created Scaleway resource and put the
    run back in the queue (or fail it if attempts are exhausted).
    """
    orphaned = await RunRepository.get_orphaned_provisioning()
    if not orphaned:
        return
    logger.warning(
        "recovering {} orphaned provisioning run(s) from previous process",
        len(orphaned),
    )
    for run_id in orphaned:
        asyncio.create_task(_recover_orphaned_provisioning_run(run_id))


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


async def _abort_stuck_provisioning(run_id) -> None:
    logger.warning(
        "run {} stuck in provisioning for > {} min — force destroy",
        run_id,
        settings.run_provisioning_timeout_minutes,
    )
    await release_node(run_id)


async def reap_stuck_provisioning() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(
        minutes=settings.run_provisioning_timeout_minutes
    )
    stuck = await RunRepository.claim_provisioning_timed_out(cutoff)
    for run_id in stuck:
        asyncio.create_task(_abort_stuck_provisioning(run_id))


async def poll_once() -> None:
    global _in_flight_provisions
    claimed = await RunRepository.claim_queued(limit=_free_provision_slots())
    # Reserve slots before yielding so concurrent poll ticks see the new count.
    _in_flight_provisions += len(claimed)
    for run_id, gpu_type_required in claimed:
        asyncio.create_task(handle_queued_run(run_id, gpu_type_required))
    await reap_stuck_provisioning()
    await reap_stuck_running()


async def polling_loop() -> None:
    await recover_leaked_nodes()
    await recover_orphaned_provisioning()
    while True:
        try:
            await poll_once()
        except Exception:
            logger.exception("orchestrator poll error")
        await asyncio.sleep(settings.poll_interval_seconds)
