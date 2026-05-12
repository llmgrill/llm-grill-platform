"""Tests for bench_service.submit()."""

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from src.models import Engine, GpuType, Run, RunStatus
from src.services import bench_service


def _make_entries(*models):
    return [bench_service.ModelEntry(model=m, engine="vllm", size_b=8) for m in models]


@pytest.fixture(autouse=True)
def skip_hf_check(monkeypatch):
    monkeypatch.setattr(bench_service, "_check_hf_exists", lambda model_id: None)


@pytest.fixture(autouse=True)
def patch_models(monkeypatch):
    """Override _load_models per test via the `model_entries` fixture."""
    pass


class TestSubmit:
    async def test_should_create_runs_for_all_models(
        self, session_factory, monkeypatch
    ):
        """
        Given: Empty DB and two models in models.yaml
        When: submit() is called
        Then: Two queued runs are created with correct fields
        """
        monkeypatch.setattr(
            bench_service,
            "_load_models",
            lambda: _make_entries(
                "meta-llama/Llama-3.1-8B-Instruct",
                "Qwen/Qwen2.5-7B-Instruct",
            ),
        )

        result = await bench_service.submit()

        assert len(result["submitted"]) == 2
        assert result["skipped"] == []

        async with session_factory() as session:
            runs = (await session.execute(select(Run))).scalars().all()

        assert {r.model for r in runs} == {
            "meta-llama/Llama-3.1-8B-Instruct",
            "Qwen/Qwen2.5-7B-Instruct",
        }
        assert all(r.status == RunStatus.queued for r in runs)

    async def test_should_skip_model_with_active_run(
        self, session_factory, monkeypatch
    ):
        """
        Given: A queued run for Llama already in DB
        When: submit() is called with the same model
        Then: No duplicate run created
        """
        async with session_factory() as session:
            session.add(
                Run(
                    model="meta-llama/Llama-3.1-8B-Instruct",
                    model_size_b=8,
                    engine=Engine.vllm,
                    gpu_type_required=GpuType.L40S,
                    scenario_path="scenarios/basic_8b.yaml",
                    status=RunStatus.queued,
                )
            )
            await session.commit()

        monkeypatch.setattr(
            bench_service,
            "_load_models",
            lambda: _make_entries("meta-llama/Llama-3.1-8B-Instruct"),
        )

        result = await bench_service.submit()

        assert result["submitted"] == []
        assert len(result["skipped"]) == 1

        async with session_factory() as session:
            runs = (await session.execute(select(Run))).scalars().all()
        assert len(runs) == 1

    async def test_should_skip_completed_run_without_force(
        self, session_factory, monkeypatch
    ):
        """
        Given: A done run for Llama in DB
        When: submit() is called without force
        Then: No new run created
        """
        async with session_factory() as session:
            session.add(
                Run(
                    model="meta-llama/Llama-3.1-8B-Instruct",
                    model_size_b=8,
                    engine=Engine.vllm,
                    gpu_type_required=GpuType.L40S,
                    scenario_path="scenarios/basic_8b.yaml",
                    status=RunStatus.done,
                )
            )
            await session.commit()

        monkeypatch.setattr(
            bench_service,
            "_load_models",
            lambda: _make_entries("meta-llama/Llama-3.1-8B-Instruct"),
        )

        result = await bench_service.submit(force=False)

        assert result["submitted"] == []
        assert len(result["skipped"]) == 1

    async def test_should_reenqueue_completed_run_with_force(
        self, session_factory, monkeypatch
    ):
        """
        Given: A done run for Llama in DB
        When: submit(force=True) is called
        Then: A new queued run is created
        """
        async with session_factory() as session:
            session.add(
                Run(
                    model="meta-llama/Llama-3.1-8B-Instruct",
                    model_size_b=8,
                    engine=Engine.vllm,
                    gpu_type_required=GpuType.L40S,
                    scenario_path="scenarios/basic_8b.yaml",
                    status=RunStatus.done,
                )
            )
            await session.commit()

        monkeypatch.setattr(
            bench_service,
            "_load_models",
            lambda: _make_entries("meta-llama/Llama-3.1-8B-Instruct"),
        )

        result = await bench_service.submit(force=True)

        assert len(result["submitted"]) == 1

        async with session_factory() as session:
            runs = (await session.execute(select(Run))).scalars().all()
        statuses = {r.status for r in runs}
        assert RunStatus.queued in statuses

    async def test_should_pass_gguf_file_for_llamacpp(
        self, session_factory, monkeypatch
    ):
        """
        Given: A llamacpp model entry with gguf_file set
        When: submit() is called
        Then: The created run has gguf_file set correctly
        """
        monkeypatch.setattr(
            bench_service,
            "_load_models",
            lambda: [
                bench_service.ModelEntry(
                    model="bartowski/Llama-3.1-8B-Instruct-GGUF",
                    engine="llamacpp",
                    size_b=8,
                    gguf_file="Llama-3.1-8B-Instruct-Q4_K_M.gguf",
                )
            ],
        )

        await bench_service.submit()

        async with session_factory() as session:
            runs = (await session.execute(select(Run))).scalars().all()

        assert len(runs) == 1
        assert runs[0].gguf_file == "Llama-3.1-8B-Instruct-Q4_K_M.gguf"
        assert runs[0].engine == Engine.llamacpp


class TestSubmitModelFilter:
    async def test_should_submit_only_matching_models(
        self, session_factory, monkeypatch
    ):
        """
        Given: Two models and a filter matching only one
        When: submit(model_filter=...) is called
        Then: Only the matching model is enqueued
        """
        monkeypatch.setattr(
            bench_service,
            "_load_models",
            lambda: _make_entries(
                "meta-llama/Llama-3.1-8B-Instruct", "Qwen/Qwen2.5-7B-Instruct"
            ),
        )

        result = await bench_service.submit(model_filter="llama")

        assert len(result["submitted"]) == 1
        async with session_factory() as session:
            runs = (await session.execute(select(Run))).scalars().all()
        assert runs[0].model == "meta-llama/Llama-3.1-8B-Instruct"

    async def test_should_raise_404_when_filter_matches_nothing(self, monkeypatch):
        """
        Given: A filter that matches no model
        When: submit(model_filter=...) is called
        Then: HTTP 404 is raised
        """
        monkeypatch.setattr(
            bench_service,
            "_load_models",
            lambda: _make_entries("meta-llama/Llama-3.1-8B-Instruct"),
        )

        with pytest.raises(HTTPException) as exc:
            await bench_service.submit(model_filter="nonexistent")
        assert exc.value.status_code == 404


class TestSubmitHFExistence:
    async def test_should_raise_422_when_hf_repo_not_found(
        self, session_factory, monkeypatch
    ):
        """
        Given: A model whose HF repo does not exist
        When: submit() is called
        Then: HTTP 422 is raised
        """
        monkeypatch.setattr(
            bench_service,
            "_load_models",
            lambda: _make_entries("missing/model"),
        )
        monkeypatch.setattr(
            bench_service,
            "_check_hf_exists",
            lambda model_id: (_ for _ in ()).throw(
                HTTPException(
                    status_code=422,
                    detail=f"Model not found on HuggingFace: {model_id}",
                )
            ),
        )

        with pytest.raises(HTTPException) as exc:
            await bench_service.submit()
        assert exc.value.status_code == 422
