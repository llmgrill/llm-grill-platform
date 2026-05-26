"""
Tests for the runs API and orchestrator polling logic.

Covers: run creation, retrieval, listing, status filtering,
and the GPU node assignment loop.
"""

import uuid

import pytest

from src.models import GpuType, Node, NodeStatus, Result, Run, RunStatus
from src.orchestrator import handle_queued_run
from src.services.run_service import RunService


def _make_result(run_id: uuid.UUID) -> Result:
    return Result(
        id=uuid.uuid4(),
        run_id=run_id,
        model="meta-llama/Llama-3-8B",
        engine="vllm",
        gpu_type=GpuType.L40S,
        scenario="scenarios/basic.yaml",
        total_requests=10,
        success_count=10,
        error_count=0,
        success_rate=1.0,
        ttft_mean_s=0.1,
        ttft_median_s=0.1,
        ttft_p95_s=0.2,
        tpot_mean_s=0.03,
        e2e_mean_s=0.4,
        e2e_p95_s=0.6,
        tokens_per_second_mean=40.0,
        total_tokens_per_second=100.0,
        requests_per_second=2.5,
        total_duration_s=4.0,
    )


SMALL_MODEL_PAYLOAD = {
    "model": "meta-llama/Llama-3-8B",
    "model_size_b": 8,
    "engine": "vllm",
    "scenario_path": "scenarios/basic.yaml",
}

LARGE_MODEL_PAYLOAD = {
    "model": "meta-llama/Llama-3-70B",
    "model_size_b": 70,
    "engine": "vllm",
    "scenario_path": "scenarios/basic.yaml",
}


class TestRunCreation:
    """Tests for POST /runs."""

    async def test_should_create_run_with_queued_status(self, client):
        """
        Should persist a new run and return it as queued.

        Given: A valid run payload for an 8B model
        When: POST /runs is called
        Then: 201 response with a UUID, status=queued, gpu_count=1
        """
        # When
        resp = await client.post("/runs", json=SMALL_MODEL_PAYLOAD)

        # Then
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "queued"
        assert uuid.UUID(data["id"])
        assert data["gpu_count"] == 1

    async def test_should_auto_assign_gpu_type_from_model_size(self, client):
        """
        Should set gpu_type_required automatically based on model_size_b.

        Given: An 8B model payload
        When: POST /runs is called
        Then: gpu_type_required is L40S (routed automatically)
        """
        # When
        resp = await client.post("/runs", json=SMALL_MODEL_PAYLOAD)

        # Then
        assert resp.json()["gpu_type_required"] == "L40S"

    async def test_should_reject_non_positive_model_size(self, client):
        """
        Should return 422 when model_size_b is zero or negative.

        Given: A payload with model_size_b=0
        When: POST /runs is called
        Then: 422 Unprocessable Entity
        """
        # Given
        bad_payload = {**SMALL_MODEL_PAYLOAD, "model_size_b": 0}

        # When
        resp = await client.post("/runs", json=bad_payload)

        # Then
        assert resp.status_code == 422


class TestRunRetrieval:
    """Tests for GET /runs/{id}."""

    async def test_should_return_run_by_id(self, client):
        """
        Should return the run matching the given UUID.

        Given: A run was created
        When: GET /runs/{id} is called with the returned UUID
        Then: 200 with the same run id
        """
        # Given
        run_id = (await client.post("/runs", json=SMALL_MODEL_PAYLOAD)).json()["id"]

        # When
        resp = await client.get(f"/runs/{run_id}")

        # Then
        assert resp.status_code == 200
        assert resp.json()["id"] == run_id

    async def test_should_return_404_when_run_does_not_exist(self, client):
        """
        Should return 404 for an unknown run UUID.

        Given: No run exists with the given id
        When: GET /runs/{id} is called
        Then: 404 Not Found
        """
        # When
        resp = await client.get(f"/runs/{uuid.uuid4()}")

        # Then
        assert resp.status_code == 404


class TestRunListing:
    """Tests for GET /runs."""

    async def test_should_list_all_runs(self, client):
        """
        Should return all runs regardless of status.

        Given: Two runs created with different model sizes
        When: GET /runs is called without filter
        Then: Both runs are returned
        """
        # Given
        await client.post("/runs", json=SMALL_MODEL_PAYLOAD)
        await client.post("/runs", json=LARGE_MODEL_PAYLOAD)

        # When
        resp = await client.get("/runs")

        # Then
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    async def test_should_filter_runs_by_status(self, client):
        """
        Should return only runs matching the requested status.

        Given: One queued run exists
        When: GET /runs?status=queued and GET /runs?status=running
        Then: One result for queued, zero for running
        """
        # Given
        await client.post("/runs", json=SMALL_MODEL_PAYLOAD)

        # When / Then
        assert len((await client.get("/runs?status=queued")).json()) == 1
        assert len((await client.get("/runs?status=running")).json()) == 0


class TestOrchestratorProvisioning:
    """Tests for ephemeral node provisioning via handle_queued_run."""

    async def test_should_provision_node_and_mark_run_running(
        self, session_factory, queued_run, mocker
    ):
        """
        Should provision a node via Terraform and transition run to running.

        Given: A queued H100 run and a stubbed provision_node returning fake ids
        When: handle_queued_run is called
        Then: Run is running, node is busy, started_at is set
        """
        # Given
        mocker.patch(
            "src.orchestrator.provision_node",
            return_value=("scw-instance-abc", "1.2.3.4"),
        )
        async with session_factory() as session:
            run = await session.get(Run, queued_run)
            gpu_type = run.gpu_type_required
        await handle_queued_run(queued_run, gpu_type)

        # Then
        async with session_factory() as session:
            run = await session.get(Run, queued_run)
            node = await session.get(Node, "scw-instance-abc")
        assert run.status == RunStatus.running
        assert run.started_at is not None
        assert node is not None
        assert node.status == NodeStatus.busy
        assert node.ip_address == "1.2.3.4"

    async def test_should_mark_run_failed_when_provision_raises(
        self, session_factory, queued_run, mocker
    ):
        """
        Should mark run as failed when Terraform provisioning fails.

        Given: provision_node raises an exception
        When: handle_queued_run is called
        Then: Run status is failed, ended_at is set
        """
        # Given
        mocker.patch(
            "src.orchestrator.provision_node",
            side_effect=RuntimeError("terraform apply failed"),
        )
        async with session_factory() as session:
            run = await session.get(Run, queued_run)
            gpu_type = run.gpu_type_required
        await handle_queued_run(queued_run, gpu_type)

        # Then
        async with session_factory() as session:
            run = await session.get(Run, queued_run)
        assert run.status == RunStatus.failed
        assert run.ended_at is not None


class TestRunCompletion:
    """Tests for POST /runs/{id}/complete and /fail endpoints."""

    async def _create_running_run(self, client, session_factory) -> str:
        resp = await client.post("/runs", json=SMALL_MODEL_PAYLOAD)
        run_id = resp.json()["id"]
        async with session_factory() as session:
            run = await session.get(Run, uuid.UUID(run_id))
            run.status = RunStatus.running
            await session.commit()
        return run_id

    async def test_should_mark_run_done_on_complete(
        self, client, session_factory, mocker
    ):
        """
        Should set status=done and store results when runner reports completion.

        Given: A running run
        When: POST /runs/{id}/complete is called with JSONL results
        Then: Run status is done, results_jsonl is stored, ended_at is set
        """
        # Given
        mocker.patch("src.controllers.run_controller.release_node")
        mocker.patch(
            "src.services.run_service.upload_results",
            return_value="runs/x/results.jsonl",
        )
        mocker.patch("src.services.run_service.upload_meta")
        mocker.patch("src.services.run_service.update_leaderboard_for")
        run_id = await self._create_running_run(client, session_factory)
        mocker.patch(
            "src.services.run_service.aggregate",
            return_value=_make_result(uuid.UUID(run_id)),
        )

        # When
        resp = await client.post(
            f"/runs/{run_id}/complete",
            json={"results_jsonl": '{"tokens_per_second": 42}\n'},
        )

        # Then
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "done"
        assert data["results_url"] is not None
        assert data["ended_at"] is not None

    async def test_should_mark_run_failed_on_fail(
        self, client, session_factory, mocker
    ):
        """
        Should set status=failed and store error when runner reports failure.

        Given: A running run
        When: POST /runs/{id}/fail is called with an error message
        Then: Run status is failed, error_message is stored
        """
        # Given
        mocker.patch("src.controllers.run_controller.release_node")
        run_id = await self._create_running_run(client, session_factory)

        # When
        resp = await client.post(
            f"/runs/{run_id}/fail",
            json={"error_message": "OOM during warmup"},
        )

        # Then
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "failed"
        assert data["error_message"] == "OOM during warmup"

    async def test_should_return_404_when_completing_unknown_run(self, client, mocker):
        """
        Should return 404 when completing a run that does not exist.

        Given: No run with the given id
        When: POST /runs/{id}/complete is called
        Then: 404 Not Found
        """
        # Given
        mocker.patch("src.controllers.run_controller.release_node")
        mocker.patch(
            "src.services.run_service.upload_results",
            return_value="runs/x/results.jsonl",
        )

        # When
        resp = await client.post(
            f"/runs/{uuid.uuid4()}/complete",
            json={"results_jsonl": "{}"},
        )

        # Then
        assert resp.status_code == 404

    async def test_should_return_404_when_failing_unknown_run(self, client, mocker):
        """
        Should return 404 when failing a run that does not exist.

        Given: No run with the given id
        When: POST /runs/{id}/fail is called
        Then: 404 Not Found
        """
        # Given
        mocker.patch("src.controllers.run_controller.release_node")

        # When
        resp = await client.post(
            f"/runs/{uuid.uuid4()}/fail",
            json={"error_message": "OOM"},
        )

        # Then
        assert resp.status_code == 404

    async def test_should_reject_fail_on_done_run(
        self, client, session_factory, mocker
    ):
        """
        Should return 409 when trying to fail a run that is already done.

        Given: A run with status=done
        When: POST /runs/{id}/fail is called
        Then: 409 Conflict
        """
        # Given
        mocker.patch("src.controllers.run_controller.release_node")
        resp = await client.post("/runs", json=SMALL_MODEL_PAYLOAD)
        run_id = resp.json()["id"]
        async with session_factory() as session:
            run = await session.get(Run, uuid.UUID(run_id))
            run.status = RunStatus.done
            await session.commit()

        # When
        resp = await client.post(
            f"/runs/{run_id}/fail",
            json={"error_message": "late failure"},
        )

        # Then
        assert resp.status_code == 409

    async def test_should_reject_complete_on_non_running_run(self, client, mocker):
        """
        Should return 409 when trying to complete a run that is not running.

        Given: A queued run
        When: POST /runs/{id}/complete is called
        Then: 409 Conflict
        """
        # Given
        mocker.patch("src.controllers.run_controller.release_node")
        mocker.patch(
            "src.services.run_service.upload_results",
            return_value="runs/x/results.jsonl",
        )
        resp = await client.post("/runs", json=SMALL_MODEL_PAYLOAD)
        run_id = resp.json()["id"]
        mocker.patch(
            "src.services.run_service.aggregate",
            return_value=_make_result(uuid.UUID(run_id)),
        )

        # When
        resp = await client.post(
            f"/runs/{run_id}/complete",
            json={"results_jsonl": "{}"},
        )

        # Then
        assert resp.status_code == 409


class TestGpuRouting:
    """Unit tests for the GPU routing logic (threshold: < 26B → L40S, else H100)."""

    @pytest.mark.parametrize("model_size_b", [3, 7, 8, 13, 25])
    def test_should_route_below_threshold_to_l40s(self, model_size_b):
        """
        Should return L40S for any model strictly below 26B.

        Given: A model size in billions below the 26B threshold
        When: select_gpu is called
        Then: GpuType.L40S is returned
        """
        assert RunService.select_gpu(model_size_b) == GpuType.L40S

    @pytest.mark.parametrize("model_size_b", [26, 30, 70, 405])
    def test_should_route_at_or_above_threshold_to_h100(self, model_size_b):
        """
        Should return H100 for any model at or above 26B.

        Given: A model size in billions at or above the 26B threshold
        When: select_gpu is called
        Then: GpuType.H100 is returned
        """
        assert RunService.select_gpu(model_size_b) == GpuType.H100
