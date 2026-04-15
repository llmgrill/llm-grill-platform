from __future__ import annotations

import json
from pathlib import Path

from pipeline.adapters.storage.filesystem_results_repository import (
    FilesystemResultsRepository,
    InMemoryResultsRepository,
)
from pipeline.application.services.aggregation_service import AggregationService

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES = REPO_ROOT / "results" / "fixtures"


def _load_fixture(slug: str, backend: str) -> list[dict]:
    path = FIXTURES / "2026-04-14" / slug / f"{backend}.jsonl"
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def test_aggregate_given_fixture_data_when_run_then_writes_schema_conformant_leaderboard():
    # Given
    repo = InMemoryResultsRepository()
    repo.write_jsonl(
        "2026-04-14",
        "meta-llama--Llama-3.1-8B-Instruct",
        "vllm",
        _load_fixture("meta-llama--Llama-3.1-8B-Instruct", "vllm"),
    )
    repo.write_jsonl(
        "2026-04-14",
        "meta-llama--Llama-3.1-8B-Instruct",
        "llamacpp",
        _load_fixture("meta-llama--Llama-3.1-8B-Instruct", "llamacpp"),
    )
    repo.write_jsonl(
        "2026-04-14",
        "Qwen--Qwen2.5-7B-Instruct",
        "vllm",
        _load_fixture("Qwen--Qwen2.5-7B-Instruct", "vllm"),
    )

    # When
    AggregationService(repo).aggregate()

    # Then
    assert repo.leaderboard is not None
    assert len(repo.leaderboard) == 3
    entry = next(
        e
        for e in repo.leaderboard
        if e["model"] == "meta-llama/Llama-3.1-8B-Instruct" and e["backend"] == "vllm"
    )
    expected_keys = {
        "model",
        "backend",
        "date",
        "ttft_mean",
        "ttft_p95",
        "tpot_mean",
        "e2e_mean",
        "tokens_per_sec",
        "success_rate",
        "n_requests",
    }
    assert expected_keys.issubset(entry.keys())
    assert entry["date"] == "2026-04-14"
    assert entry["backend"] in {"vllm", "llamacpp"}
    assert 0.0 <= entry["success_rate"] <= 1.0
    assert entry["n_requests"] > 0


def test_aggregate_given_fixture_data_when_run_then_writes_per_model_detail_with_conversations():
    # Given
    repo = InMemoryResultsRepository()
    repo.write_jsonl(
        "2026-04-14",
        "meta-llama--Llama-3.1-8B-Instruct",
        "vllm",
        _load_fixture("meta-llama--Llama-3.1-8B-Instruct", "vllm"),
    )

    # When
    AggregationService(repo).aggregate()

    # Then
    detail = repo.models["meta-llama--Llama-3.1-8B-Instruct"]
    assert detail["model"] == "meta-llama/Llama-3.1-8B-Instruct"
    assert len(detail["runs"]) == 1
    run = detail["runs"][0]
    assert run["backend"] == "vllm"
    convs = {c["name"] for c in run["conversations"]}
    assert convs.issubset({"short-qa", "coding", "multi-turn", "long-context"})
    for c in run["conversations"]:
        assert set(c["metrics"].keys()) == {
            "ttft_mean",
            "ttft_p95",
            "tpot_mean",
            "e2e_mean",
            "tokens_per_sec",
            "success_rate",
            "n_requests",
        }


def test_aggregate_given_multiple_dates_when_run_then_history_is_sorted_ascending():
    # Given
    repo = InMemoryResultsRepository()
    row = {
        "scenario": "nightly",
        "server": "vllm",
        "model": "org/M",
        "conversation": "short-qa",
        "turn": 0,
        "iteration": 0,
        "ttft_ms": 10.0,
        "tpot_ms": 5.0,
        "e2e_ms": 100.0,
        "prompt_tokens": 10,
        "completion_tokens": 10,
        "tokens_per_second": 80.0,
        "success": True,
    }
    repo.write_jsonl("2026-04-10", "org--M", "vllm", [row])
    repo.write_jsonl("2026-04-14", "org--M", "vllm", [row])

    # When
    AggregationService(repo).aggregate()

    # Then
    series = repo.history["series"]
    assert len(series) == 1
    dates = [p["date"] for p in series[0]["points"]]
    assert dates == sorted(dates)


def test_aggregate_given_filesystem_repo_when_run_then_writes_three_files(tmp_path):
    # Given
    repo = FilesystemResultsRepository(root=tmp_path, read_roots=[FIXTURES])
    # When
    AggregationService(repo).aggregate()
    # Then
    assert (tmp_path / "aggregated" / "leaderboard.json").exists()
    assert (tmp_path / "aggregated" / "history.json").exists()
    assert (tmp_path / "aggregated" / "models").is_dir()
    assert list((tmp_path / "aggregated" / "models").glob("*.json"))
