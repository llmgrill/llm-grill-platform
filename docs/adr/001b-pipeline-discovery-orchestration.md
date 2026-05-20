# ADR 001b: Pipeline — Model List and Orchestration

**Date:** 2026-03-25
**Status:** Revised 2026-05-11
**Parent:** [ADR 001](001-automated-benchmark-site.md)

---

## Context

The pipeline must:
1. Maintain a curated list of models to benchmark.
2. Skip models already benchmarked for the current date.
3. Orchestrate infra provisioning → benchmark → results commit.

Automatic HuggingFace discovery was considered but dropped in favour of a simple hardcoded list (`models.yaml`). This keeps the pipeline auditable and avoids burning GPU time on unknown models.

## Decision

**Hardcoded model list + GitHub Actions CI.**

No `discover.py`. No scheduled cron. The pipeline triggers on two events:
- A push that modifies `models.yaml` → runs only the new / missing models.
- A manual `workflow_dispatch` with optional `force=true` → re-runs everything.

## Design

### Model list (`models.yaml`)

Single source of truth at the repo root. Adding a model = opening a PR that edits this file.

```yaml
models:
  - model: meta-llama/Llama-3.1-8B-Instruct
    engine: vllm
    size_b: 8
  - model: bartowski/Qwen2.5-14B-Instruct-GGUF
    engine: llamacpp
    size_b: 14
    gguf_file: Qwen2.5-14B-Instruct-Q4_K_M.gguf
```

Fields:
- `model` — HuggingFace ID (`org/name`)
- `engine` — `vllm` or `llamacpp`
- `size_b` — model size in billions (used to select GPU type)
- `scenario` — optional, defaults to `scenarios/ramp.yaml`
- `gguf_file` — llamacpp only, specific GGUF filename to download

### GitHub Actions (`.github/workflows/bench.yml`)

Triggers:
```yaml
on:
  push:
    paths: [orchestrator/models.yaml]
  workflow_dispatch:
    inputs:
      force: { type: boolean, default: false }
      model: { type: string, default: "" }   # partial HF ID match
```

Steps (high-level — see [`.github/workflows/bench.yml`](../../.github/workflows/bench.yml) for the source of truth):
1. `terraform apply` — spin up the ephemeral orchestrator VM.
2. `rsync` repo + `.env` + `docker compose up` postgres / migrations / orchestrator.
3. `curl -X POST /bench` — queue all new/missing (model, engine) pairs.
4. Poll `GET /bench/status` until `active=0`.
5. `curl /leaderboard` → upload to `s3://${SCW_BUCKET}/leaderboard.json`.
6. `terraform destroy` — tear down the orchestrator VM (`always()`).

No standalone `scripts/bench.py` or `wait_for_runs.py`: the orchestrator owns the diff (`/bench` consumes `orchestrator/models.yaml`) and the run lifecycle.

### Orchestrator (FastAPI)

Unchanged. Accepts `POST /runs`, provisions GPU nodes via Terraform, runs `runner.sh`, reports back. See [ADR 001a](001a-infra-terraform-scaleway.md) for infra details.

### Deduplication

Existing terminal-state run in Postgres for the `(model, engine)` pair = benchmark done. Skipped at `/bench` time via `RunRepository.has_completed_run`. Pass `force=true` to override.

## Consequences

| | |
|---|---|
| **+** | Fully auditable model list, no surprise GPU spend, simple dedup, easy to add/remove models via PR |
| **−** | No automatic discovery of new models — someone must maintain `models.yaml` manually |
| **Risks** | Long-running CI job (3h `timeout-minutes` on the `bench` job); mitigated by orchestrator-side watchdogs (`RUN_PROVISIONING_TIMEOUT_MINUTES`, `RUN_RUNNING_TIMEOUT_MINUTES`) that fail stuck runs server-side |
