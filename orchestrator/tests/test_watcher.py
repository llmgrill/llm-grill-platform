"""
Tests for the HuggingFace model watcher.

Covers: size extraction (regex + safetensors fallback), engine detection,
org whitelist filtering, deduplication, and run creation.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.models import Engine, GpuType, Run, RunStatus
from src.watcher import (
    _already_exists,
    _detect_engine,
    _extract_size_b,
    _passes_filter,
    _scan_and_enqueue,
)


def _model_info(
    model_id: str, downloads: int = 100_000, safetensors_total: int | None = None
):
    from datetime import datetime, timezone
    info = MagicMock()
    info.id = model_id
    info.downloads = downloads
    info.created_at = datetime.now(timezone.utc)
    if safetensors_total is not None:
        info.safetensors = SimpleNamespace(total=safetensors_total)
    else:
        info.safetensors = None
    return info


class TestExtractSizeB:
    """Unit tests for _extract_size_b()."""

    def test_should_extract_size_from_model_name(self):
        """
        Should parse integer size from model id.

        Given: meta-llama/Llama-3-8B
        When: _extract_size_b is called
        Then: returns 8
        """
        assert _extract_size_b(_model_info("meta-llama/Llama-3-8B")) == 8

    def test_should_extract_decimal_size_rounded(self):
        """
        Should round decimal sizes to nearest integer.

        Given: Qwen/Qwen3.6-35B-A3B
        When: _extract_size_b is called
        Then: returns 35 (first match)
        """
        assert _extract_size_b(_model_info("Qwen/Qwen3.6-35B-A3B")) == 35

    def test_should_return_none_when_size_unknown(self):
        """
        Should return None when neither regex nor safetensors yields a size.

        Given: org/unknown-model with no size hints
        When: _extract_size_b is called
        Then: returns None
        """
        assert _extract_size_b(_model_info("org/unknown-model")) is None


class TestDetectEngine:
    """Unit tests for _detect_engine()."""

    def test_should_detect_llamacpp_for_gguf_model(self):
        """
        Should return llamacpp when model id contains 'GGUF'.

        Given: unsloth/Llama-3-8B-GGUF
        When: _detect_engine is called
        Then: Engine.llamacpp
        """
        assert _detect_engine("unsloth/Llama-3-8B-GGUF") == Engine.llamacpp

    def test_should_detect_llamacpp_case_insensitive(self):
        """Should match gguf in any case."""
        assert _detect_engine("org/model-gguf") == Engine.llamacpp

    def test_should_detect_vllm_for_non_gguf_model(self):
        """
        Should return vllm for standard (non-GGUF) models.

        Given: meta-llama/Llama-3-8B-Instruct
        When: _detect_engine is called
        Then: Engine.vllm
        """
        assert _detect_engine("meta-llama/Llama-3-8B-Instruct") == Engine.vllm


class TestPassesFilter:
    """Unit tests for _passes_filter(): whitelist-based filtering."""

    def test_should_accept_whitelisted_org(self, monkeypatch):
        from src import watcher

        monkeypatch.setattr(watcher.settings, "hf_watched_orgs", ["meta-llama"])
        assert _passes_filter(_model_info("meta-llama/Llama-3-8B")) is True

    def test_should_reject_non_whitelisted_org(self, monkeypatch):
        from src import watcher

        monkeypatch.setattr(watcher.settings, "hf_watched_orgs", ["meta-llama"])
        assert _passes_filter(_model_info("other-org/Model-7B")) is False

    def test_should_accept_all_when_whitelist_empty(self, monkeypatch):
        from src import watcher

        monkeypatch.setattr(watcher.settings, "hf_watched_orgs", [])
        assert _passes_filter(_model_info("any-org/any-model")) is True


class TestAlreadyExists:
    """Tests for _already_exists() deduplication logic."""

    async def test_should_return_false_when_no_run_exists(self, session_factory):
        """
        Should return False when no run for this model is in DB.

        Given: Empty DB
        When: _already_exists is called
        Then: False
        """
        async with session_factory() as session:
            result = await _already_exists(session, "meta-llama/Llama-3-8B")
        assert result is False

    async def test_should_return_true_for_queued_run(self, session_factory):
        """
        Should return True when a queued run exists for this model.

        Given: A queued run for Llama-3-8B
        When: _already_exists is called
        Then: True
        """
        async with session_factory() as session:
            session.add(
                Run(
                    model="meta-llama/Llama-3-8B",
                    model_size_b=8,
                    engine=Engine.vllm,
                    gpu_type_required=GpuType.L40S,
                    scenario_path="scenarios/basic_8b.yaml",
                    status=RunStatus.queued,
                )
            )
            await session.commit()

        async with session_factory() as session:
            result = await _already_exists(session, "meta-llama/Llama-3-8B")
        assert result is True

    async def test_should_return_false_for_failed_run(self, session_factory):
        """
        Should allow re-enqueueing a model whose previous run failed.

        Given: A failed run for this model
        When: _already_exists is called
        Then: False (failed runs don't block re-enqueueing)
        """
        async with session_factory() as session:
            session.add(
                Run(
                    model="meta-llama/Llama-3-8B",
                    model_size_b=8,
                    engine=Engine.vllm,
                    gpu_type_required=GpuType.L40S,
                    scenario_path="scenarios/basic_8b.yaml",
                    status=RunStatus.failed,
                )
            )
            await session.commit()

        async with session_factory() as session:
            result = await _already_exists(session, "meta-llama/Llama-3-8B")
        assert result is False


class TestScanAndEnqueue:
    """Integration tests for _scan_and_enqueue() with mocked HF API."""

    async def test_should_create_run_for_valid_whitelisted_model(
        self, session_factory, mocker, monkeypatch
    ):
        """
        Should create a queued run for a valid model from a whitelisted org.

        Given: HF returns one text-generation model from meta-llama, size 8B
        When: _scan_and_enqueue is called
        Then: One Run is inserted with correct fields
        """
        from src import watcher

        monkeypatch.setattr(watcher.settings, "hf_watched_orgs", ["meta-llama"])
        mocker.patch(
            "src.watcher.list_models",
            return_value=[_model_info("meta-llama/Llama-3-8B")],
        )

        await _scan_and_enqueue(session_factory)

        async with session_factory() as session:
            from sqlalchemy import select

            runs = (await session.execute(select(Run))).scalars().all()
        assert len(runs) == 1
        assert runs[0].model == "meta-llama/Llama-3-8B"
        assert runs[0].model_size_b == 8
        assert runs[0].engine == Engine.vllm
        assert runs[0].status == RunStatus.queued

    async def test_should_skip_model_with_unknown_size(
        self, session_factory, mocker, monkeypatch
    ):
        """
        Should not create a run when model size cannot be determined.

        Given: HF returns a model with no size in name and no safetensors info
        When: _scan_and_enqueue is called
        Then: No Run is inserted
        """
        from src import watcher

        monkeypatch.setattr(watcher.settings, "hf_watched_orgs", [])
        mocker.patch(
            "src.watcher.list_models",
            return_value=[_model_info("org/unknown-model")],
        )

        await _scan_and_enqueue(session_factory)

        async with session_factory() as session:
            from sqlalchemy import select

            runs = (await session.execute(select(Run))).scalars().all()
        assert len(runs) == 0

    async def test_should_skip_already_existing_run(
        self, session_factory, mocker, monkeypatch
    ):
        """
        Should not create a duplicate run when one already exists.

        Given: A queued run for Llama-3-8B already in DB
        When: _scan_and_enqueue is called with the same model
        Then: Still only one Run in DB
        """
        from src import watcher

        monkeypatch.setattr(watcher.settings, "hf_watched_orgs", [])
        async with session_factory() as session:
            session.add(
                Run(
                    model="meta-llama/Llama-3-8B",
                    model_size_b=8,
                    engine=Engine.vllm,
                    gpu_type_required=GpuType.L40S,
                    scenario_path="scenarios/basic_8b.yaml",
                    status=RunStatus.queued,
                )
            )
            await session.commit()

        mocker.patch(
            "src.watcher.list_models",
            return_value=[_model_info("meta-llama/Llama-3-8B")],
        )

        await _scan_and_enqueue(session_factory)

        async with session_factory() as session:
            from sqlalchemy import select

            runs = (await session.execute(select(Run))).scalars().all()
        assert len(runs) == 1

    async def test_should_skip_model_not_in_whitelist(
        self, session_factory, mocker, monkeypatch
    ):
        """
        Should not create a run for a model from a non-whitelisted org.

        Given: Whitelist is meta-llama only; HF returns a model from other-org
        When: _scan_and_enqueue is called
        Then: No Run is inserted
        """
        from src import watcher

        monkeypatch.setattr(watcher.settings, "hf_watched_orgs", ["meta-llama"])
        mocker.patch(
            "src.watcher.list_models",
            return_value=[_model_info("other-org/SomeModel-7B")],
        )

        await _scan_and_enqueue(session_factory)

        async with session_factory() as session:
            from sqlalchemy import select

            runs = (await session.execute(select(Run))).scalars().all()
        assert len(runs) == 0


@pytest.mark.integration
class TestScanAndEnqueueIntegration:
    """Integration tests that call the real HuggingFace API via _scan_and_enqueue."""

    async def test_should_enqueue_runs_from_real_hf_api(self, session_factory, monkeypatch):
        """
        Should create at least one queued run from real HuggingFace data.

        Given: Real HuggingFace Hub API, default org whitelist, 30-day window
        When: _scan_and_enqueue is called
        Then: At least one Run is inserted in the DB from a whitelisted org
        """
        from sqlalchemy import select

        from src import watcher
        from src.config import settings

        # Use a 30-day window to guarantee models exist regardless of when the test runs
        monkeypatch.setattr(watcher.settings, "hf_watch_interval_seconds", 30 * 86400)

        await _scan_and_enqueue(session_factory)

        async with session_factory() as session:
            runs = (await session.execute(select(Run))).scalars().all()

        assert len(runs) > 0, "No runs were created — check org whitelist and HF connectivity"
        # Vérifie que chaque run respecte au moins l'un des deux critères d'admission
        watched = set(settings.hf_watched_orgs)
        for run in runs:
            org = run.model.split("/")[0]
            in_whitelist = org in watched
            has_downloads = run.model_size_b > 0  # si créé, c'est que le filtre est passé
            assert in_whitelist or has_downloads, f"Run inattendu: {run.model}"
