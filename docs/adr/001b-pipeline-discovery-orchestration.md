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

### Scripts

```
scripts/
├── bench.py           # Read models.yaml, diff vs results/, POST to orchestrator
└── wait_for_runs.py   # Poll orchestrator until all runs reach terminal state, save JSONL
```

**`bench.py`** deduplication: `results/YYYY-MM-DD/{slug}/{engine}.jsonl` exists → skip. Pass `--force` to override.

**`wait_for_runs.py`** polls `/runs?status=...` every 30 s, downloads completed JSONL from `results_url`, exits non-zero on any failure.

### GitHub Actions (`.github/workflows/bench.yml`)

Triggers:
```yaml
on:
  push:
    paths: [models.yaml]
  workflow_dispatch:
    inputs:
      force: { type: boolean, default: false }
      model: { type: string, default: "" }   # partial HF ID match
```

Steps: install deps → `bench.py` → `wait_for_runs.py` → `git commit results/` → `git push`

Required secrets: `ORCHESTRATOR_URL`, `HF_TOKEN`

### Orchestrator (FastAPI)

Unchanged. Accepts `POST /runs`, provisions GPU nodes via Terraform, runs `runner.sh`, reports back. See [ADR 001a](001a-infra-terraform-scaleway.md) for infra details.

### Deduplication

File existence = benchmark done: `results/YYYY-MM-DD/{slug}/{engine}.jsonl`.

## Consequences

| | |
|---|---|
| **+** | Fully auditable model list, no surprise GPU spend, simple dedup, easy to add/remove models via PR |
| **−** | No automatic discovery of new models — someone must maintain `models.yaml` manually |
| **Risks** | Long-running CI job (2h timeout set in workflow); mitigated by `wait_for_runs.py` hard timeout |
