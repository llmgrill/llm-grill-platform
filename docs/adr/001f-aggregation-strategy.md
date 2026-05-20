# ADR 001f: Aggregation Strategy — Single Source of Truth

**Date:** 2026-03-25
**Status:** Validated — design carried over after storage migration ([ADR 001c](001c-data-storage-jsonl.md) superseded). Decision unchanged: a single Python aggregation step feeds the frontend.
**Parent:** [ADR 001](001-automated-benchmark-site.md)

---

## Context

ADR 001c and 001d both flag the same issue: aggregation logic (percentiles, success filtering, tokens/s) would be duplicated between Python (`llm_grill/metrics.py`) and JavaScript. This creates a divergence risk — the site and CLI could show different numbers for the same data.

## Options Considered

| Option | Description | Verdict |
|--------|-------------|---------|
| **A. Python pre-aggregation in the pipeline** | `aggregate.py` writes JSON; site just copies it | **Chosen** |
| B. Keep both, add cross-validation tests | Two implementations + test harness | Rejected: more work than one implementation, tests can drift too |
| C. Shared WASM module | Compile aggregation to WASM for both runtimes | Rejected: massive over-engineering for percentile math |

## Decision

**Option A**: Single Python aggregation step. The site consumes pre-built JSON.

## Design

### `orchestrator/src/aggregation.py`

Called by the `GET /leaderboard` endpoint. Reuses `llm_grill.metrics` semantics, queries the `results` table in Postgres, and returns one JSON document per request.

The `bench` CI workflow fetches `/leaderboard`, uploads it as `s3://${SCW_BUCKET}/leaderboard.json` (public-read), and the frontend (when built) consumes that URL directly.

| Output | Source | Content |
|--------|--------|---------|
| `s3://${SCW_BUCKET}/leaderboard.json` | `GET /leaderboard` → S3 upload in [`.github/workflows/bench.yml`](../../.github/workflows/bench.yml) | Latest run per (model, backend) with mean/p95 TTFT, tokens/s, success rate |

History and per-model views were initially planned (`models/{slug}.json`, `history.json`) but are not implemented today; if needed they would follow the same pattern (DB query → S3 upload).

### Flow

```
runner (GPU VM) → POST /runs/{id}/complete (metrics) → Postgres
CI               → GET  /leaderboard → S3 upload (leaderboard.json)
frontend         → fetch leaderboard.json from S3 at runtime
```

## Consequences

| | |
|---|---|
| **+** | Single source of truth (`llm_grill/metrics.py`), no JS aggregation to maintain, site build is a simple copy, CLI and site always agree |
| **−** | Extra pipeline step (fast — seconds). Changing aggregation logic requires re-running on historical data (one-time migration) |
