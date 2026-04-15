# results/

Source-of-truth store for all benchmark data (see [ADR 001c](../docs/adr/001c-data-storage-jsonl.md)).

## Layout

```
results/
├── YYYY-MM-DD/{org}--{name}/{backend}.jsonl   # raw benchmark output
├── aggregated/                                 # pre-computed JSON for the frontend
│   ├── leaderboard.json
│   ├── history.json
│   └── models/{slug}.json
└── fixtures/YYYY-MM-DD/...                     # synthetic reference data for tests
```

## Conventions

- **Date**: `YYYY-MM-DD`, the calendar date of the nightly run.
- **Slug**: HuggingFace `{org}/{name}` → `{org}--{name}` (e.g. `meta-llama/Llama-3.1-8B-Instruct` → `meta-llama--Llama-3.1-8B-Instruct`).
- **Backend file**: one JSONL per backend (`vllm.jsonl`, `llamacpp.jsonl`). `llamacpp.jsonl` is absent when the model has no GGUF quantisation.

## JSONL format

Each line is one `RequestMetrics` record from `llm_grill.metrics`. The authoritative schema lives in that package.

## Deduplication

File existence = benchmark done. The pipeline skips `{date}/{slug}/{backend}.jsonl` if the file already exists.

## Aggregated output

The frontend consumes only `results/aggregated/`; it never reads the raw JSONL. Contract: [`docs/schemas.md`](../docs/schemas.md).
