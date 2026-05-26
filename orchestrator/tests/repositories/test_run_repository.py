"""
Tests for RunRepository against an in-memory SQLite DB.

The session_factory fixture (conftest) swaps src.db.AsyncSessionLocal for an
aiosqlite session, so every static method exercises real SQLAlchemy queries
without a live Postgres. State-machine transitions, dedup helpers, and the
reaper/retry paths are all covered here.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from src import db
from src.models import Engine, GpuType, Result, Run, RunStatus
from src.repositories.run_repository import RunRepository


async def _add_run(**overrides) -> Run:
    """Persist a Run with sane defaults, return the managed (refreshed) row."""
    defaults = dict(
        model="test/model",
        model_size_b=8,
        engine=Engine.vllm,
        gpu_type_required=GpuType.L40S,
        scenario_path="scenarios/ramp.yaml",
    )
    defaults.update(overrides)
    run = Run(**defaults)
    async with db.AsyncSessionLocal() as session:
        session.add(run)
        await session.commit()
        await session.refresh(run)
    return run


async def _get(run_id: uuid.UUID) -> Run:
    """Fetch a run, asserting it exists — narrows Run | None for the type checker."""
    run = await RunRepository.get(run_id)
    assert run is not None
    return run


def _result(run: Run) -> Result:
    return Result(
        run_id=run.id,
        model=run.model,
        engine="vllm",
        gpu_type=GpuType.L40S,
        scenario="scenarios/ramp.yaml",
        total_requests=10,
        success_count=10,
        error_count=0,
        success_rate=1.0,
        ttft_mean_s=0.1,
        ttft_median_s=0.1,
        ttft_p95_s=0.2,
        tpot_mean_s=0.01,
        e2e_mean_s=1.0,
        e2e_p95_s=1.5,
        tokens_per_second_mean=30.0,
        total_tokens_per_second=300.0,
        requests_per_second=4.0,
        total_duration_s=10.0,
    )


class TestGetAndGetAll:
    async def test_get_returns_none_when_absent(self, session_factory):
        """Given an unknown id, When get, Then None."""
        assert await RunRepository.get(uuid.uuid4()) is None

    async def test_get_all_filters_by_status(self, session_factory):
        """Given runs in mixed states, When get_all(queued), Then only queued."""
        # Given
        await _add_run(status=RunStatus.queued)
        await _add_run(status=RunStatus.done)

        # When
        queued = await RunRepository.get_all(status=RunStatus.queued)
        every = await RunRepository.get_all()

        # Then
        assert len(queued) == 1
        assert queued[0].status == RunStatus.queued
        assert len(every) == 2


class TestClaimQueued:
    async def test_returns_empty_for_non_positive_limit(self, session_factory):
        """Given limit<=0, When claim_queued, Then no DB hit, empty list."""
        assert await RunRepository.claim_queued(0) == []

    async def test_transitions_claimed_runs_to_provisioning(self, session_factory):
        """
        Given two queued runs and limit=1
        When  claim_queued
        Then  exactly one run is returned and flipped to provisioning
        """
        # Given
        await _add_run(status=RunStatus.queued)
        await _add_run(status=RunStatus.queued)

        # When
        claimed = await RunRepository.claim_queued(1)

        # Then
        assert len(claimed) == 1
        run_id, gpu = claimed[0]
        assert gpu == GpuType.L40S
        run = await _get(run_id)
        assert run.status == RunStatus.provisioning


class TestHasActiveRun:
    async def test_true_when_active(self, session_factory):
        """Given a running run, When has_active_run, Then True."""
        await _add_run(status=RunStatus.running)
        assert await RunRepository.has_active_run("test/model", "vllm") is True

    async def test_false_when_only_terminal(self, session_factory):
        """Given only a done run, When has_active_run, Then False."""
        await _add_run(status=RunStatus.done)
        assert await RunRepository.has_active_run("test/model", "vllm") is False


class TestCountByStatus:
    async def test_zero_filled_then_counted(self, session_factory):
        """Given two queued + one failed, When count_by_status, Then all keys present."""
        # Given
        await _add_run(status=RunStatus.queued)
        await _add_run(status=RunStatus.queued)
        await _add_run(status=RunStatus.failed)

        # When
        counts = await RunRepository.count_by_status()

        # Then
        assert counts["queued"] == 2
        assert counts["failed"] == 1
        assert counts["running"] == 0


class TestCompleteAndFail:
    async def test_complete_run_sets_done_and_persists_result(self, session_factory):
        """Given a running run, When complete_run, Then done + result stored."""
        # Given
        run = await _add_run(status=RunStatus.running)

        # When
        done = await RunRepository.complete_run(run.id, "s3://x", _result(run))

        # Then
        assert done.status == RunStatus.done
        assert done.results_url == "s3://x"
        assert done.ended_at is not None

    async def test_complete_run_raises_for_unknown(self, session_factory):
        """Given an unknown id, When complete_run, Then ValueError."""
        run = await _add_run()
        with pytest.raises(ValueError):
            await RunRepository.complete_run(uuid.uuid4(), "s3://x", _result(run))

    async def test_fail_run_sets_failed_with_message(self, session_factory):
        """Given a run, When fail_run, Then failed + error_message set."""
        run = await _add_run(status=RunStatus.running)
        failed = await RunRepository.fail_run(run.id, "boom")
        assert failed.status == RunStatus.failed
        assert failed.error_message == "boom"

    async def test_fail_run_raises_for_unknown(self, session_factory):
        """Given an unknown id, When fail_run, Then ValueError."""
        with pytest.raises(ValueError):
            await RunRepository.fail_run(uuid.uuid4(), "boom")


class TestStateTransitions:
    async def test_save_merges_detached_run(self, session_factory):
        """Given a detached run with edits, When save, Then persisted."""
        run = await _add_run()
        run.error_message = "edited"
        saved = await RunRepository.save(run)
        assert saved.error_message == "edited"

    async def test_set_provisioning(self, session_factory):
        run = await _add_run(status=RunStatus.queued)
        await RunRepository.set_provisioning(run.id)
        assert (await _get(run.id)).status == RunStatus.provisioning

    async def test_set_provisioning_raises_for_unknown(self, session_factory):
        with pytest.raises(ValueError):
            await RunRepository.set_provisioning(uuid.uuid4())

    async def test_set_running_stamps_started_at(self, session_factory):
        run = await _add_run(status=RunStatus.provisioning)
        ts = datetime.now(timezone.utc)
        await RunRepository.set_running(run.id, ts)
        refreshed = await _get(run.id)
        assert refreshed.status == RunStatus.running
        assert refreshed.started_at is not None

    async def test_set_running_raises_for_unknown(self, session_factory):
        with pytest.raises(ValueError):
            await RunRepository.set_running(uuid.uuid4(), datetime.now(timezone.utc))

    async def test_set_logs_url(self, session_factory):
        run = await _add_run()
        await RunRepository.set_logs_url(run.id, "s3://logs")
        assert (await _get(run.id)).logs_url == "s3://logs"

    async def test_set_logs_url_raises_for_unknown(self, session_factory):
        with pytest.raises(ValueError):
            await RunRepository.set_logs_url(uuid.uuid4(), "s3://logs")

    async def test_set_failed_with_message(self, session_factory):
        run = await _add_run(status=RunStatus.running)
        ts = datetime.now(timezone.utc)
        await RunRepository.set_failed(run.id, ts, "explicit error")
        refreshed = await _get(run.id)
        assert refreshed.status == RunStatus.failed
        assert refreshed.error_message == "explicit error"

    async def test_set_failed_without_message_keeps_existing(self, session_factory):
        run = await _add_run(status=RunStatus.running, error_message="prior")
        await RunRepository.set_failed(run.id, datetime.now(timezone.utc))
        assert (await _get(run.id)).error_message == "prior"

    async def test_set_failed_raises_for_unknown(self, session_factory):
        with pytest.raises(ValueError):
            await RunRepository.set_failed(uuid.uuid4(), datetime.now(timezone.utc))


class TestReapers:
    async def test_claim_running_timed_out(self, session_factory):
        """Given a running run started before cutoff, When claimed, Then failed."""
        # Given
        old = datetime.now(timezone.utc) - timedelta(hours=2)
        run = await _add_run(status=RunStatus.running, started_at=old)

        # When
        ids = await RunRepository.claim_running_timed_out(
            datetime.now(timezone.utc) - timedelta(hours=1)
        )

        # Then
        assert run.id in ids
        assert (await _get(run.id)).status == RunStatus.failed

    async def test_get_orphaned_provisioning(self, session_factory):
        """Given a provisioning run, When get_orphaned_provisioning, Then its id."""
        run = await _add_run(status=RunStatus.provisioning)
        ids = await RunRepository.get_orphaned_provisioning()
        assert ids == [run.id]

    async def test_claim_provisioning_timed_out(self, session_factory):
        """Given an old provisioning run, When claimed, Then failed."""
        # Given
        old = datetime.now(timezone.utc) - timedelta(hours=2)
        run = await _add_run(status=RunStatus.provisioning, created_at=old)

        # When
        ids = await RunRepository.claim_provisioning_timed_out(
            datetime.now(timezone.utc) - timedelta(hours=1)
        )

        # Then
        assert run.id in ids
        assert (await _get(run.id)).status == RunStatus.failed


class TestRequeueForRetry:
    async def test_requeues_when_under_max(self, session_factory):
        """Given attempts below max, When requeue, Then queued + count returned."""
        run = await _add_run(status=RunStatus.provisioning)
        attempts = await RunRepository.requeue_for_retry(run.id, max_attempts=3)
        assert attempts == 1
        assert (await _get(run.id)).status == RunStatus.queued

    async def test_returns_none_at_max(self, session_factory):
        """Given attempts reaching max, When requeue, Then None (no requeue)."""
        run = await _add_run(status=RunStatus.provisioning, provision_attempts=2)
        result = await RunRepository.requeue_for_retry(run.id, max_attempts=3)
        assert result is None
        assert (await _get(run.id)).status == RunStatus.provisioning

    async def test_raises_for_unknown(self, session_factory):
        with pytest.raises(ValueError):
            await RunRepository.requeue_for_retry(uuid.uuid4(), max_attempts=3)
