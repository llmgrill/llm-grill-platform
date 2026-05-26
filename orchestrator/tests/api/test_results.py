"""
Tests for the /results API endpoints and aggregation integration.

Covers: GET /results/{run_id}, GET /results/{run_id}/download,
and POST /runs/{id}/complete with aggregation + storage.
"""

import uuid

import pytest

from src.models import Engine, GpuType, Result, Run, RunStatus


def _make_result(run_id: uuid.UUID, **kwargs) -> Result:
    defaults = dict(
        id=uuid.uuid4(),
        run_id=run_id,
        model="meta-llama/Llama-3-8B",
        engine="vllm",
        gpu_type=GpuType.L40S,
        scenario="scenarios/basic_8b.yaml",
        total_requests=100,
        success_count=99,
        error_count=1,
        success_rate=0.99,
        ttft_mean_s=0.12,
        ttft_median_s=0.11,
        ttft_p95_s=0.25,
        tpot_mean_s=0.03,
        e2e_mean_s=0.50,
        e2e_p95_s=0.80,
        tokens_per_second_mean=45.0,
        total_tokens_per_second=120.0,
        requests_per_second=3.5,
        total_duration_s=28.6,
    )
    return Result(**{**defaults, **kwargs})


async def _create_run(session_factory) -> uuid.UUID:
    async with session_factory() as session:
        run = Run(
            model="meta-llama/Llama-3-8B",
            model_size_b=8,
            engine=Engine.vllm,
            gpu_type_required=GpuType.L40S,
            scenario_path="scenarios/basic_8b.yaml",
            status=RunStatus.done,
        )
        session.add(run)
        await session.commit()
        return run.id


async def _insert_result(session_factory, run_id: uuid.UUID) -> Result:
    async with session_factory() as session:
        result = _make_result(run_id)
        session.add(result)
        await session.commit()
        return result


class TestResultsEndpoints:
    """Tests for GET /results/{run_id}."""

    async def test_should_return_result_by_run_id(self, client, session_factory):
        """
        Should return the result matching the given run_id.

        Given: A result linked to a specific run
        When: GET /results/{run_id} is called
        Then: 200 with correct metrics
        """
        # Given
        run_id = await _create_run(session_factory)
        await _insert_result(session_factory, run_id)

        # When
        resp = await client.get(f"/results/{run_id}")

        # Then
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_requests"] == 100
        assert data["success_rate"] == pytest.approx(0.99)
        assert data["tokens_per_second_mean"] == pytest.approx(45.0)

    async def test_should_return_404_when_result_not_found(self, client):
        """
        Should return 404 for an unknown run_id.

        Given: No result exists for the given UUID
        When: GET /results/{run_id} is called
        Then: 404 Not Found
        """
        # When
        resp = await client.get(f"/results/{uuid.uuid4()}")

        # Then
        assert resp.status_code == 404

    async def test_should_return_presigned_url_for_download(
        self, client, session_factory, mocker
    ):
        """
        Should return a presigned URL for direct JSONL download.

        Given: A result exists and presigned_url returns a fake URL
        When: GET /results/{run_id}/download is called
        Then: 200 with a url field
        """
        # Given
        run_id = await _create_run(session_factory)
        await _insert_result(session_factory, run_id)
        mocker.patch(
            "src.services.result_service.presigned_url",
            return_value="https://s3.fr-par.scw.cloud/llmgrill-results/runs/fake/results.jsonl",
        )

        # When
        resp = await client.get(f"/results/{run_id}/download")

        # Then
        assert resp.status_code == 200
        assert "url" in resp.json()
        assert resp.json()["url"].startswith("https://")


class TestRunCompleteIntegration:
    """Integration tests for POST /runs/{id}/complete with aggregation + storage."""

    async def _create_running_run(self, client, session_factory) -> str:
        resp = await client.post(
            "/runs",
            json={
                "model": "meta-llama/Llama-3-8B",
                "model_size_b": 8,
                "engine": "vllm",
                "scenario_path": "scenarios/basic_8b.yaml",
            },
        )
        run_id = resp.json()["id"]
        async with session_factory() as session:
            run = await session.get(Run, uuid.UUID(run_id))
            run.status = RunStatus.running
            await session.commit()
        return run_id

    async def test_should_store_results_url_and_create_result_row(
        self, client, session_factory, mocker
    ):
        """
        Should upload JSONL to storage, aggregate metrics, and persist a Result row.

        Given: A running run and mocked upload_results + aggregate
        When: POST /runs/{id}/complete is called with JSONL
        Then: run.results_url is set, a Result row exists
        """
        # Given
        mocker.patch("src.controllers.run_controller.release_node")
        mocker.patch(
            "src.services.run_service.upload_results",
            return_value="runs/fake-id/results.jsonl",
        )
        mocker.patch("src.services.run_service.upload_meta")
        mocker.patch("src.services.run_service.update_leaderboard_for")
        run_id = await self._create_running_run(client, session_factory)
        fake_result = _make_result(uuid.UUID(run_id))
        mocker.patch("src.services.run_service.aggregate", return_value=fake_result)

        # When
        resp = await client.post(
            f"/runs/{run_id}/complete",
            json={"results_jsonl": "{}"},
        )

        # Then
        assert resp.status_code == 200
        assert resp.json()["results_url"] == "runs/fake-id/results.jsonl"

        async with session_factory() as session:
            from sqlalchemy import select

            rows = (await session.execute(select(Result))).scalars().all()
        assert len(rows) == 1
        assert rows[0].success_rate == pytest.approx(0.99)
