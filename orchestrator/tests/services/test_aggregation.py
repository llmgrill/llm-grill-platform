"""
Tests for the aggregation layer — delegates to llm_grill.aggregate.

Covers: correct field mapping from AggregatedMetrics to Result.
"""

import uuid
from unittest.mock import MagicMock

import pytest

from src.aggregation import aggregate
from src.models import Engine, GpuType, Result, Run


def _make_run() -> Run:
    return Run(
        id=uuid.uuid4(),
        model="meta-llama/Llama-3-8B",
        model_size_b=8,
        engine=Engine.vllm,
        gpu_type_required=GpuType.L40S,
        scenario_path="scenarios/basic.yaml",
    )


def _make_metrics(**overrides) -> MagicMock:
    m = MagicMock()
    m.scenario = "scenarios/basic.yaml"
    m.total_requests = 100
    m.success_count = 99
    m.error_count = 1
    m.success_rate = 0.99
    m.ttft_mean_s = 0.12
    m.ttft_median_s = 0.11
    m.ttft_p95_s = 0.25
    m.tpot_mean_s = 0.03
    m.e2e_mean_s = 0.50
    m.e2e_p95_s = 0.80
    m.tokens_per_second_mean = 45.0
    m.total_tokens_per_second = 120.0
    m.requests_per_second = 3.5
    m.total_duration_s = 28.6
    for k, v in overrides.items():
        setattr(m, k, v)
    return m


class TestAggregate:
    """Tests for aggregate() — maps llm_grill.AggregatedMetrics to a Result row."""

    def test_should_return_result_with_correct_fields(self, mocker):
        """
        Should map all AggregatedMetrics fields onto the Result model.

        Given: llm_grill.aggregate returns a fake AggregatedMetrics object
        When: aggregate is called with JSONL and a run
        Then: A Result with correct run_id, model, engine, gpu_type, and metrics
        """
        # Given
        run = _make_run()
        metrics = _make_metrics()
        mocker.patch(
            "src.aggregation.RequestMetrics.model_validate_json",
            return_value=MagicMock(e2e_latency_s=0.5),
        )
        mocker.patch("src.aggregation._aggregate", return_value=metrics)
        mocker.patch("src.aggregation.estimate_total_duration", return_value=0.5)

        # When
        result = aggregate("{}", run)

        # Then
        assert isinstance(result, Result)
        assert result.run_id == run.id
        assert result.model == run.model
        assert result.engine == run.engine.value
        assert result.gpu_type == GpuType(run.gpu_type_required)
        assert result.success_rate == 0.99
        assert result.total_tokens_per_second == 120.0

    def test_should_pass_jsonl_to_llm_grill(self, mocker):
        """
        Should forward the JSONL string to llm_grill.aggregate unchanged.

        Given: llm_grill.aggregate is mocked
        When: aggregate is called with a specific JSONL string
        Then: llm_grill.aggregate is called with that exact string
        """
        # Given
        run = _make_run()
        metrics = _make_metrics()
        fake_request = MagicMock(e2e_latency_s=0.5)
        mocker.patch(
            "src.aggregation.RequestMetrics.model_validate_json",
            return_value=fake_request,
        )
        mock_agg = mocker.patch("src.aggregation._aggregate", return_value=metrics)
        mocker.patch("src.aggregation.estimate_total_duration", return_value=1.0)
        jsonl = '{"tokens": 42}\n{"tokens": 38}\n'

        # When
        aggregate(jsonl, run)

        # Then
        assert mock_agg.call_count == 1
        called_results, called_duration = mock_agg.call_args[0]
        assert called_results == [fake_request, fake_request]
        assert called_duration == pytest.approx(1.0)

    @pytest.mark.parametrize("jsonl", ["", "   \n\t  \n"])
    def test_should_handle_empty_or_whitespace_only_input(self, mocker, jsonl):
        """
        Given: Empty or whitespace-only JSONL
        When: aggregate is called
        Then: estimate_total_duration is skipped, _aggregate is called with an empty list
              and total_duration_s=0.0
        """
        # Given
        run = _make_run()
        metrics = _make_metrics(total_duration_s=0.0)
        mock_agg = mocker.patch("src.aggregation._aggregate", return_value=metrics)
        mock_duration = mocker.patch("src.aggregation.estimate_total_duration")

        # When
        result = aggregate(jsonl, run)

        # Then
        mock_duration.assert_not_called()
        mock_agg.assert_called_once_with([], 0.0)
        assert result.total_duration_s == 0.0
