# ADR 001c: Storage — JSONL in Git as Source of Truth

**Date:** 2026-03-25
**Status:** Proposed
**Parent:** [ADR 001](001-automated-benchmark-site.md)

---

## Context

Benchmark results must be stored durably, support historical comparison, and avoid duplicates. The format must be compatible with `llm-grill` which natively produces JSONL.

## Options Considered

| Option | Description | Verdict |
|--------|-------------|---------|
| **A. JSONL committed in Git** | One file per (date, model, backend) in `results/`. Git repo = database | **Chosen** |
| B. PostgreSQL / SQLite | Relational DB for metrics | Rejected: needs a server/file to maintain. JSONL is sufficient and directly readable by pandas/polars |
| C. S3 / Object Storage | JSONL in a bucket | Rejected: external dependency. Git provides versioning and audit trail for free |

## Decision

**Option A**: JSONL in Git.

## Design

### Layout

```
results/
├── 2026-03-21/
│   ├── meta-llama--Llama-3.1-8B-Instruct/
│   │   ├── vllm.jsonl
│   │   └── llamacpp.jsonl
│   └── Qwen--Qwen2.5-7B-Instruct/
│       └── vllm.jsonl            # no GGUF → no llamacpp
```

**Conventions**: date `YYYY-MM-DD`, model `org--name` (slash → `--`), backend `{backend}.jsonl`.

### JSONL Format

Each line is a `RequestMetrics` (defined in `llm_grill/metrics.py`) containing: identifiers (scenario, server, model, conversation, turn, iteration, user), latency metrics (TTFT, TPOT, E2E), throughput (tokens/s, prompt/completion tokens), GPU metrics (utilization, memory, temperature, power), and metadata (success, error, run_id).

### Deduplication

Existing JSONL file = benchmark already done. No need to read contents.

### Direct reading

Files remain usable without the site: `pd.read_json("results/.../vllm.jsonl", lines=True)`.

### Growth projection

~50 KB/file, ~150 KB/model, ~500 KB/night, ~15 MB/month → manageable in Git. If repo exceeds 1 GB: migrate old files to Git LFS.

## Consequences

| | |
|---|---|
| **+** | Zero storage infra, native audit trail (`git log`), compatible with pandas/polars, trivial dedup |
| **−** | No SQL queries (batch aggregation at build time). Repo grows over time (mitigation: Git LFS) |
