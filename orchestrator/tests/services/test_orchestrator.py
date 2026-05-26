"""
Tests for orchestrator logic: release_node and poll_once.

Covers: node teardown after run completion, queued-run polling,
and error handling when destroy or poll fails.
"""

import uuid

import pytest

import src.orchestrator as orch
from src.infra.terraform import (
    OutOfStockError,
    ScalewayAuthError,
    ScalewayQuotaError,
    TerraformError,
)
from src.models import Engine, GpuType, Node, NodeStatus, Run, RunStatus
from src.orchestrator import (
    _provision_under_permit,
    handle_queued_run,
    poll_once,
    reap_stuck_provisioning,
    reap_stuck_running,
    recover_leaked_nodes,
    recover_orphaned_provisioning,
    release_node,
)


async def _create_run_with_node(
    session_factory, run_id: uuid.UUID | None = None
) -> uuid.UUID:
    async with session_factory() as session:
        run = Run(
            model="meta-llama/Llama-3-8B",
            model_size_b=8,
            engine=Engine.vllm,
            gpu_type_required=GpuType.L40S,
            scenario_path="scenarios/basic.yaml",
            status=RunStatus.running,
        )
        if run_id:
            run.id = run_id
        session.add(run)
        await session.flush()
        node = Node(
            id=f"node-{run.id}",
            gpu_type=GpuType.L40S,
            status=NodeStatus.busy,
            current_run_id=run.id,
        )
        session.add(node)
        await session.commit()
        return run.id


class TestReleaseNode:
    """Tests for release_node — destroy ephemeral node after a run ends."""

    async def test_should_mark_node_down_after_destroy(self, session_factory, mocker):
        """
        Should call destroy_node and set node status to down.

        Given: A running run with an associated busy node
        When: release_node is called
        Then: Node status is down
        """
        # Given
        mocker.patch("src.orchestrator.destroy_node", return_value=None)
        run_id = await _create_run_with_node(session_factory)

        # When
        await release_node(run_id)

        # Then
        async with session_factory() as session:
            node = await session.get(Node, f"node-{run_id}")
        assert node.status == NodeStatus.down

    async def test_should_not_raise_when_destroy_fails(self, session_factory, mocker):
        """
        Should swallow destroy errors and still mark the node down.

        Given: destroy_node raises a RuntimeError
        When: release_node is called
        Then: No exception propagates, node is still marked down
        """
        # Given
        mocker.patch(
            "src.orchestrator.destroy_node", side_effect=RuntimeError("timeout")
        )
        run_id = await _create_run_with_node(session_factory)

        # When (should not raise)
        await release_node(run_id)

        # Then
        async with session_factory() as session:
            node = await session.get(Node, f"node-{run_id}")
        assert node.status == NodeStatus.down

    async def test_should_do_nothing_when_no_node_found(self, session_factory, mocker):
        """
        Should not fail when there is no node associated with the run.

        Given: A run_id with no matching node
        When: release_node is called
        Then: No exception is raised
        """
        # Given
        mocker.patch("src.orchestrator.destroy_node", return_value=None)
        run_id = uuid.uuid4()

        # When / Then (no exception)
        await release_node(run_id)


class TestPollOnce:
    """Tests for poll_once — pick up queued runs and spawn provisioning tasks."""

    async def test_should_create_task_for_each_queued_run(
        self, session_factory, mocker
    ):
        """
        Should spawn one task per queued run found.

        Given: Two queued runs in the DB
        When: poll_once is called
        Then: handle_queued_run is called twice
        """
        # Given
        async with session_factory() as session:
            for _ in range(2):
                session.add(
                    Run(
                        model="meta-llama/Llama-3-8B",
                        model_size_b=8,
                        engine=Engine.vllm,
                        gpu_type_required=GpuType.L40S,
                        scenario_path="scenarios/basic.yaml",
                        status=RunStatus.queued,
                    )
                )
            await session.commit()

        async def _noop(session, run):
            pass

        mock_handle = mocker.patch(
            "src.orchestrator.handle_queued_run", side_effect=_noop
        )

        # When
        await poll_once()

        # Then
        assert mock_handle.call_count == 2

    async def test_should_not_create_task_when_no_queued_runs(
        self, session_factory, mocker
    ):
        """
        Should not spawn any task when there are no queued runs.

        Given: Empty DB
        When: poll_once is called
        Then: handle_queued_run is not called
        """

        # Given
        async def _noop(session, run):
            pass

        mock_handle = mocker.patch(
            "src.orchestrator.handle_queued_run", side_effect=_noop
        )

        # When
        await poll_once()

        # Then
        mock_handle.assert_not_called()


@pytest.fixture
def captured_tasks(mocker):
    """Capture asyncio.create_task coroutines so tests can drain them.

    Several orchestrator entrypoints fire-and-forget background work; tests
    need to await it to assert on the resulting repo calls.
    """
    import asyncio

    created: list = []

    def _capture(coro):
        task = asyncio.ensure_future(coro)
        created.append(task)
        return task

    mocker.patch("asyncio.create_task", side_effect=_capture)
    return created


async def _drain(tasks):
    import asyncio

    if tasks:
        await asyncio.gather(*tasks)


class TestProvisionUnderPermit:
    """_provision_under_permit drives the provision → busy/running transition."""

    async def test_should_set_busy_and_running_on_success(
        self, session_factory, mocker
    ):
        """
        Given: provision_node returns an instance + IP
        When:  _provision_under_permit runs
        Then:  node is marked busy and the run transitions to running
        """
        # Given
        run = Run(
            id=uuid.uuid4(),
            model="m",
            model_size_b=8,
            engine=Engine.vllm,
            gpu_type_required=GpuType.L40S,
            scenario_path="s.yaml",
        )
        mocker.patch.object(orch.NodeRepository, "create_provisioning")
        mocker.patch.object(orch.RunRepository, "get", return_value=run)
        mocker.patch.object(orch, "provision_node", return_value=("inst-1", "1.2.3.4"))
        set_busy = mocker.patch.object(orch.NodeRepository, "set_busy")
        set_running = mocker.patch.object(orch.RunRepository, "set_running")

        # When
        await _provision_under_permit(run.id, GpuType.L40S)

        # Then
        set_busy.assert_awaited_once()
        set_running.assert_awaited_once()

    async def test_should_bail_when_run_disappeared(self, session_factory, mocker):
        """
        Given: the run vanished before provisioning (get returns None)
        When:  _provision_under_permit runs
        Then:  the half-created node is torn down and provision is skipped
        """
        # Given
        mocker.patch.object(orch.NodeRepository, "create_provisioning")
        mocker.patch.object(orch.RunRepository, "get", return_value=None)
        set_down = mocker.patch.object(orch.NodeRepository, "set_down_by_run")
        prov = mocker.patch.object(orch, "provision_node")

        # When
        await _provision_under_permit(uuid.uuid4(), GpuType.L40S)

        # Then
        set_down.assert_awaited_once()
        prov.assert_not_called()

    @pytest.mark.parametrize(
        "exc, reason_fragment",
        [
            (OutOfStockError("x"), "out of stock"),
            (ScalewayQuotaError("x"), "quota"),
        ],
    )
    async def test_should_requeue_on_capacity_errors(
        self, session_factory, mocker, exc, reason_fragment
    ):
        """
        Given: provision_node raises a capacity error and retries remain
        When:  _provision_under_permit runs
        Then:  the run is requeued and not failed
        """
        # Given
        run = Run(
            id=uuid.uuid4(),
            model="m",
            model_size_b=8,
            engine=Engine.vllm,
            gpu_type_required=GpuType.L40S,
            scenario_path="s.yaml",
        )
        mocker.patch.object(orch.NodeRepository, "create_provisioning")
        mocker.patch.object(orch.RunRepository, "get", return_value=run)
        mocker.patch.object(orch, "provision_node", side_effect=exc)
        requeue = mocker.patch.object(
            orch.RunRepository, "requeue_for_retry", return_value=1
        )
        mocker.patch.object(orch.NodeRepository, "set_down_by_run")
        set_failed = mocker.patch.object(orch.RunRepository, "set_failed")

        # When
        await _provision_under_permit(run.id, GpuType.L40S)

        # Then
        requeue.assert_awaited_once()
        set_failed.assert_not_called()

    async def test_should_fail_when_capacity_retries_exhausted(
        self, session_factory, mocker
    ):
        """
        Given: capacity error and requeue returns None (attempts exhausted)
        When:  _provision_under_permit runs
        Then:  the run is marked failed
        """
        # Given
        run = Run(
            id=uuid.uuid4(),
            model="m",
            model_size_b=8,
            engine=Engine.vllm,
            gpu_type_required=GpuType.L40S,
            scenario_path="s.yaml",
        )
        mocker.patch.object(orch.NodeRepository, "create_provisioning")
        mocker.patch.object(orch.RunRepository, "get", return_value=run)
        mocker.patch.object(orch, "provision_node", side_effect=OutOfStockError("x"))
        mocker.patch.object(orch.RunRepository, "requeue_for_retry", return_value=None)
        mocker.patch.object(orch.NodeRepository, "set_down_by_run")
        set_failed = mocker.patch.object(orch.RunRepository, "set_failed")

        # When
        await _provision_under_permit(run.id, GpuType.L40S)

        # Then
        set_failed.assert_awaited_once()

    @pytest.mark.parametrize(
        "exc",
        [ScalewayAuthError("x"), TerraformError("x"), RuntimeError("boom")],
    )
    async def test_should_fail_on_hard_provision_errors(
        self, session_factory, mocker, exc
    ):
        """
        Given: provision_node raises a non-recoverable error
        When:  _provision_under_permit runs
        Then:  the run is failed and node released (via _fail)
        """
        # Given
        run = Run(
            id=uuid.uuid4(),
            model="m",
            model_size_b=8,
            engine=Engine.vllm,
            gpu_type_required=GpuType.L40S,
            scenario_path="s.yaml",
        )
        mocker.patch.object(orch.NodeRepository, "create_provisioning")
        mocker.patch.object(orch.RunRepository, "get", return_value=run)
        mocker.patch.object(orch, "provision_node", side_effect=exc)
        set_down = mocker.patch.object(orch.NodeRepository, "set_down_by_run")
        set_failed = mocker.patch.object(orch.RunRepository, "set_failed")

        # When
        await _provision_under_permit(run.id, GpuType.L40S)

        # Then
        set_down.assert_awaited_once()
        set_failed.assert_awaited_once()


class TestHandleQueuedRun:
    """handle_queued_run wraps _provision_under_permit with a last-resort guard."""

    async def test_should_fail_run_on_unhandled_error(self, session_factory, mocker):
        """
        Given: _provision_under_permit raises unexpectedly
        When:  handle_queued_run runs
        Then:  the run is failed via _fail (guard catches it)
        """
        # Given
        mocker.patch.object(
            orch, "_provision_under_permit", side_effect=RuntimeError("kaboom")
        )
        fail = mocker.patch.object(orch, "_fail")

        # When
        await handle_queued_run(uuid.uuid4(), GpuType.L40S)

        # Then
        fail.assert_awaited_once()


class TestRecovery:
    """recover_leaked_nodes / recover_orphaned_provisioning startup paths."""

    async def test_recover_leaked_nodes_releases_each(
        self, session_factory, mocker, captured_tasks
    ):
        """
        Given: two leaked busy nodes
        When:  recover_leaked_nodes runs
        Then:  release_node is scheduled for each
        """
        # Given
        ids = [uuid.uuid4(), uuid.uuid4()]
        mocker.patch.object(orch.NodeRepository, "get_leaked", return_value=ids)
        release = mocker.patch.object(orch, "release_node")

        # When
        await recover_leaked_nodes()
        await _drain(captured_tasks)

        # Then
        assert release.call_count == 2

    async def test_recover_leaked_nodes_noop_when_empty(self, session_factory, mocker):
        """Given no leaked nodes, When recover, Then no release scheduled."""
        mocker.patch.object(orch.NodeRepository, "get_leaked", return_value=[])
        release = mocker.patch.object(orch, "release_node")
        await recover_leaked_nodes()
        release.assert_not_called()

    async def test_recover_orphaned_requeues_then_or_fails(
        self, session_factory, mocker, captured_tasks
    ):
        """
        Given: one orphaned provisioning run, requeue succeeds
        When:  recover_orphaned_provisioning runs
        Then:  the run is released and requeued (not failed)
        """
        # Given
        rid = uuid.uuid4()
        mocker.patch.object(
            orch.RunRepository, "get_orphaned_provisioning", return_value=[rid]
        )
        mocker.patch.object(orch, "release_node")
        mocker.patch.object(orch.RunRepository, "requeue_for_retry", return_value=2)
        set_failed = mocker.patch.object(orch.RunRepository, "set_failed")

        # When
        await recover_orphaned_provisioning()
        await _drain(captured_tasks)

        # Then
        set_failed.assert_not_called()

    async def test_recover_orphaned_fails_when_exhausted(
        self, session_factory, mocker, captured_tasks
    ):
        """
        Given: orphaned run with requeue returning None
        When:  recover_orphaned_provisioning runs
        Then:  the run is marked failed
        """
        # Given
        rid = uuid.uuid4()
        mocker.patch.object(
            orch.RunRepository, "get_orphaned_provisioning", return_value=[rid]
        )
        mocker.patch.object(orch, "release_node")
        mocker.patch.object(orch.RunRepository, "requeue_for_retry", return_value=None)
        set_failed = mocker.patch.object(orch.RunRepository, "set_failed")

        # When
        await recover_orphaned_provisioning()
        await _drain(captured_tasks)

        # Then
        set_failed.assert_awaited_once()

    async def test_recover_orphaned_noop_when_empty(self, session_factory, mocker):
        """Given no orphans, When recover, Then no work scheduled."""
        mocker.patch.object(
            orch.RunRepository, "get_orphaned_provisioning", return_value=[]
        )
        release = mocker.patch.object(orch, "release_node")
        await recover_orphaned_provisioning()
        release.assert_not_called()


class TestReapers:
    """reap_stuck_running / reap_stuck_provisioning watchdog paths."""

    async def test_reap_stuck_running_aborts_each(
        self, session_factory, mocker, captured_tasks
    ):
        """
        Given: one timed-out running run
        When:  reap_stuck_running runs
        Then:  it is released and failed
        """
        # Given
        rid = uuid.uuid4()
        mocker.patch.object(
            orch.RunRepository, "claim_running_timed_out", return_value=[rid]
        )
        release = mocker.patch.object(orch, "release_node")
        set_failed = mocker.patch.object(orch.RunRepository, "set_failed")

        # When
        await reap_stuck_running()
        await _drain(captured_tasks)

        # Then
        release.assert_awaited_once()
        set_failed.assert_awaited_once()

    async def test_reap_stuck_provisioning_releases_each(
        self, session_factory, mocker, captured_tasks
    ):
        """
        Given: one timed-out provisioning run
        When:  reap_stuck_provisioning runs
        Then:  the node is released
        """
        # Given
        rid = uuid.uuid4()
        mocker.patch.object(
            orch.RunRepository, "claim_provisioning_timed_out", return_value=[rid]
        )
        release = mocker.patch.object(orch, "release_node")

        # When
        await reap_stuck_provisioning()
        await _drain(captured_tasks)

        # Then
        release.assert_awaited_once()
