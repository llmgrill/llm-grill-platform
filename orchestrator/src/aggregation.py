import uuid
from itertools import groupby

from llm_grill.metrics import RequestMetrics, estimate_total_duration
from llm_grill.metrics import aggregate as _aggregate

from src.models import GpuType, Result, Run


def _parse(jsonl: str) -> list[RequestMetrics]:
    return [
        RequestMetrics.model_validate_json(line)
        for line in jsonl.splitlines()
        if line.strip()
    ]


def aggregate(jsonl: str, run: Run) -> Result:
    results = _parse(jsonl)
    total_duration_s = estimate_total_duration(results) if results else 0.0
    metrics = _aggregate(results, total_duration_s)
    return Result(
        id=uuid.uuid4(),
        run_id=run.id,
        model=run.model,
        engine=run.engine.value,
        gpu_type=GpuType(run.gpu_type_required),
        scenario=metrics.scenario,
        total_requests=metrics.total_requests,
        success_count=metrics.success_count,
        error_count=metrics.error_count,
        success_rate=metrics.success_rate,
        ttft_mean_s=metrics.ttft_mean_s,
        ttft_median_s=metrics.ttft_median_s,
        ttft_p95_s=metrics.ttft_p95_s,
        tpot_mean_s=metrics.tpot_mean_s,
        e2e_mean_s=metrics.e2e_mean_s,
        e2e_p95_s=metrics.e2e_p95_s,
        tokens_per_second_mean=metrics.tokens_per_second_mean,
        total_tokens_per_second=metrics.total_tokens_per_second,
        requests_per_second=metrics.requests_per_second,
        total_duration_s=metrics.total_duration_s,
    )


def aggregate_per_concurrency(jsonl: str) -> list[dict]:
    """Break the raw run down by concurrency level.

    The flat `aggregate()` collapses every ramp level into one point, which
    hides the most interesting signal of the benchmark (TTFT degrading from
    tens of ms at concurrency 1 to seconds at 64). This regroups the raw
    `RequestMetrics` by `concurrent_users_level` and aggregates each slice.

    Leaderboard-only: not persisted on `Result`. Returned sorted by level.
    """
    results = _parse(jsonl)
    results.sort(key=lambda r: r.concurrent_users_level)
    breakdown: list[dict] = []
    for level, group in groupby(results, key=lambda r: r.concurrent_users_level):
        slice_ = list(group)
        m = _aggregate(slice_, estimate_total_duration(slice_))
        breakdown.append(
            {
                "concurrency": level,
                "n_requests": m.total_requests,
                "success_rate": m.success_rate,
                "ttft_mean_s": m.ttft_mean_s,
                "ttft_p95_s": m.ttft_p95_s,
                "tpot_mean_s": m.tpot_mean_s,
                "e2e_mean_s": m.e2e_mean_s,
                "e2e_p95_s": m.e2e_p95_s,
                "tokens_per_second_mean": m.tokens_per_second_mean,
            }
        )
    return breakdown
