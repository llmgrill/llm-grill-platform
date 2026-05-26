# ADR 001h: S3 as the Source of Truth for Dedup and Leaderboard

**Date:** 2026-05-20
**Status:** Accepted
**Parent:** [ADR 001](001-automated-benchmark-site.md)
**Supersedes (in part):** [ADR 001c](001c-data-storage-jsonl.md) — refines the
"PostgreSQL + S3" hybrid noted in its supersession block.

---

## Context

The bench pipeline runs in an ephemeral GitHub Actions cycle: each push to
`orchestrator/models.yaml` provisions an orchestrator VM, runs the bench, then
`terraform destroy` wipes the VM **and its Postgres**. At the time of writing,
cross-cycle deduplication was keyed off `Run.status == done` in Postgres
(`RunRepository.has_completed_run`). Since the DB is wiped between cycles,
that flag is always false at boot — so every model in `models.yaml` was
re-benched on every push, paying GPU time for results that already existed on
S3 under `runs/<uuid>/results.jsonl`.

The S3 layout was also run-centric (`runs/<uuid>/`), so the "already done"
signal could not be recovered by listing S3 either: there was no way, given
`(model, engine)`, to find the matching UUID without scanning every blob.

A persistent, addressable source of truth was needed. S3 is already the only
durable store in the stack — it survives `terraform destroy`, is the eventual
data source for the frontend ([ADR 001d](001d-frontend-sveltekit.md)), and
incurs no infra to add.

## Options Considered

| Option | Description | Verdict |
|---|---|---|
| **A. S3 layout addressable by (model, engine)** | `results/<slug>/<engine>/latest.meta.json` is the dedup signal; `latest.jsonl` is the latest raw run. Run history kept under `runs/<run_id>/`. | **Chosen** |
| B. Add a persistent DB (managed Postgres) | Keep DB-based dedup, externalise the DB | Rejected: extra paid infra, new failure mode, doubles the source of truth with S3 (which we need anyway for the frontend) |
| C. Commit `latest.meta.json` markers back into the Git repo | Echo of ADR 001c (JSONL-in-Git) | Rejected: bench → push → re-trigger loop, branch protection conflicts, no atomic write |

## Decision

**Option A.** S3 holds the dedup signal and the published leaderboard. Postgres
remains only for **intra-cycle** state (queued/running/active runs, per-run
metrics for inspection at `/results/{run_id}`); it is never consulted to decide
whether a model has already been benched.

## Design

### Layout

```
s3://<bucket>/
├── leaderboard.json                       # consolidated, public-read
└── results/<model-slug>/<engine>/
    ├── latest.jsonl                       # raw RequestMetrics of the last `done` run
    ├── latest.meta.json                   # CompletedRunMeta — the dedup signal
    └── runs/<run_id>/
        ├── results.jsonl
        └── runner.log
```

- `<model-slug>` = `model.replace("/", "__")`. Double underscore so the slug
  decodes unambiguously (`split("__", 1)` is exact; `-` would collide with
  legitimate hyphens in model names).
- `latest.*` is what dedup and the frontend read; `runs/<run_id>/` keeps the
  full history for `/runs/{id}` debugging and a future `/history` page.

### Dedup contract

`bench_service.submit()` checks `head_latest_meta(model, engine)` (a HEAD on
`latest.meta.json`). True → model is skipped. `force=true` bypasses the check.
Manual re-bench of a single model: `aws s3 rm latest.meta.json`.

### Leaderboard

`leaderboard.json` is updated **incrementally** by
`storage.update_leaderboard_for(run, result)` at the end of
`RunService.complete()`: read current JSON, drop any stale entry for
`(model, engine)`, append the fresh one, upload back. Cheaper than recomputing
from `latest.jsonl` and idempotent across retries. Marked `public-read` so the
static frontend fetches it straight from S3, bypassing the orchestrator.

`/leaderboard` on the orchestrator now serves `leaderboard.json` from S3 with a
60-second in-memory TTL cache, instead of querying the DB.

### Schema

`CompletedRunMeta` (Pydantic, in `src/schemas.py`):

```json
{
  "run_id": "uuid",
  "model": "org/name",
  "engine": "vllm | llamacpp",
  "scenario": "scenarios/...yaml",
  "completed_at": "ISO 8601",
  "git_sha": "optional"
}
```

### Versioning

Bucket-level S3 versioning is enabled on the `scaleway_object_bucket`
resource in `infra/orchestrator-vm/main.tf` (not configured manually in the
console), so it is reproducible and version-controlled. Cheap insurance
against a corrupted `latest.jsonl` written by a buggy run.

Expiring non-current versions is **not** terraformed: the Scaleway provider's
`lifecycle_rule` only supports `expiration` / `transition` /
`abort_incomplete_multipart_upload_days`, not the AWS-style
`noncurrent_version_expiration`. The versioned objects (`latest.jsonl`,
`latest.meta.json`) are tiny, so unbounded growth is negligible. If it ever
matters, apply the policy against the raw S3 API:

```bash
aws s3api put-bucket-lifecycle-configuration \
  --bucket "$SCW_BUCKET" --endpoint-url "https://s3.$SCW_REGION.scw.cloud" \
  --lifecycle-configuration '{"Rules":[{"ID":"expire-noncurrent","Status":"Enabled","Filter":{},"NoncurrentVersionExpiration":{"NoncurrentDays":30}}]}'
```

## Consequences

| | |
|---|---|
| **+** | Dedup survives VM destruction; CI cycles only bench *new* entries in `models.yaml` |
| **+** | `leaderboard.json` is always live and public-read — unblocks the static frontend ([ADR 001d](001d-frontend-sveltekit.md)) |
| **+** | `latest.jsonl` is addressable without knowing the run UUID — debugging via `aws s3 cp` is trivial |
| **+** | Pre-built leaderboard means `/leaderboard` is O(1) and survives a cold DB |
| **−** | Concurrent run completions race on the leaderboard upsert (last writer wins). Acceptable: the orchestrator finalises one run at a time today, and the dropped entry is the most recent one we'd have published anyway |
| **−** | Re-bench of a single model is a manual `aws s3 rm` (no `DELETE /results/<model>/<engine>` endpoint — judged not worth the surface for an occasional op) |
| **−** | `Result` table is now write-only for per-run inspection; its leaderboard query (`get_latest_per_combination`) was deleted |
