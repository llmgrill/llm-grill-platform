"""Aggregation of raw JSONL results into the three frontend JSON files.

The authoritative output contract is ``docs/schemas.md``. Latency values in
JSONL fixtures are in milliseconds under keys ``ttft_ms``, ``tpot_ms``,
``e2e_ms`` with throughput under ``tokens_per_second``. When ``llm-grill`` is
installed, ``llm_grill.metrics.aggregate()`` is invoked as a sanity check (it
operates on its own ``RequestMetrics`` dataclass and is not the source of the
schema fields documented in ``docs/schemas.md``; see README of this package).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from statistics import mean, quantiles
from typing import Any

from pipeline.application.ports.results_repository_port import ResultsRepositoryPort

_VALID_CONVERSATIONS = {"short-qa", "coding", "multi-turn", "long-context"}


@dataclass
class AggregationService:
    results: ResultsRepositoryPort

    def aggregate(
        self, extra_runs: list[tuple[str, str, str, list[dict[str, Any]]]] | None = None
    ) -> None:
        """Read all runs from the repository (+ optional externally-provided rows for dry-run)
        and write leaderboard, per-model detail and history JSON."""

        # (date, slug, backend) -> rows
        corpus: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for date, slug, backend in self.results.list_runs():
            corpus[(date, slug, backend)] = self.results.read_jsonl(date, slug, backend)
        for date, slug, backend, rows in extra_runs or []:
            corpus[(date, slug, backend)] = rows

        # Leaderboard: latest date per (model, backend)
        latest: dict[tuple[str, str], tuple[str, list[dict[str, Any]]]] = {}
        for (date, slug, backend), rows in corpus.items():
            model_id = _model_from_rows(rows, slug)
            key = (model_id, backend)
            if key not in latest or date > latest[key][0]:
                latest[key] = (date, rows)

        leaderboard = [
            {
                "model": model_id,
                "backend": backend,
                "date": date,
                **_run_metrics(rows),
            }
            for (model_id, backend), (date, rows) in sorted(latest.items())
        ]
        self.results.write_aggregated_leaderboard(leaderboard)

        # Per-model detail
        by_model: dict[str, list[tuple[str, str, list[dict[str, Any]]]]] = defaultdict(
            list
        )
        for (date, slug, backend), rows in corpus.items():
            model_id = _model_from_rows(rows, slug)
            by_model[model_id].append((date, backend, rows))

        for model_id, runs in by_model.items():
            slug = model_id.replace("/", "--")
            sorted_runs = sorted(runs, key=lambda t: (t[0], t[1]))
            detail = {
                "model": model_id,
                "runs": [
                    {
                        "date": date,
                        "backend": backend,
                        "metrics": _run_metrics(rows),
                        "conversations": _conversation_metrics(rows),
                    }
                    for date, backend, rows in sorted_runs
                ],
            }
            self.results.write_aggregated_model(slug, detail)

        # History: (model, backend) time series
        series_map: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for (date, slug, backend), rows in corpus.items():
            model_id = _model_from_rows(rows, slug)
            m = _run_metrics(rows)
            series_map[(model_id, backend)].append(
                {
                    "date": date,
                    "ttft_mean": m["ttft_mean"],
                    "tokens_per_sec": m["tokens_per_sec"],
                }
            )
        history = {
            "series": [
                {
                    "model": model_id,
                    "backend": backend,
                    "points": sorted(points, key=lambda p: p["date"]),
                }
                for (model_id, backend), points in sorted(series_map.items())
            ]
        }
        self.results.write_aggregated_history(history)


def _run_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {
            "ttft_mean": None,
            "ttft_p95": None,
            "tpot_mean": None,
            "e2e_mean": None,
            "tokens_per_sec": None,
            "success_rate": 0.0,
            "n_requests": 0,
        }
    ok = [r for r in rows if r.get("success")]
    ttft = [float(r["ttft_ms"]) for r in ok if r.get("ttft_ms") is not None]
    tpot = [float(r["tpot_ms"]) for r in ok if r.get("tpot_ms") is not None]
    e2e = [float(r["e2e_ms"]) for r in ok if r.get("e2e_ms") is not None]
    tps = [
        float(r["tokens_per_second"])
        for r in ok
        if r.get("tokens_per_second") is not None
    ]
    return {
        "ttft_mean": mean(ttft) if ttft else None,
        "ttft_p95": _p95(ttft) if ttft else None,
        "tpot_mean": mean(tpot) if tpot else None,
        "e2e_mean": mean(e2e) if e2e else None,
        "tokens_per_sec": mean(tps) if tps else None,
        "success_rate": len(ok) / n,
        "n_requests": n,
    }


def _conversation_metrics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        name = r.get("conversation")
        if name in _VALID_CONVERSATIONS:
            groups[name].append(r)
    return [
        {"name": name, "metrics": _run_metrics(rs)}
        for name, rs in sorted(groups.items())
    ]


def _p95(values: list[float]) -> float:
    if len(values) < 2:
        return values[0]
    return quantiles(values, n=20)[18]


def _model_from_rows(rows: list[dict[str, Any]], fallback_slug: str) -> str:
    for r in rows:
        m = r.get("model")
        if m:
            return str(m)
    return fallback_slug.replace("--", "/")
