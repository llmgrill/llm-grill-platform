# ADR 001: LLM Benchmark Site

**Date:** 2026-03-21
**Status:** Revised 2026-05-12
**Deciders:** Gireg Roussel

---

## Context

The `llm-grill` CLI benchmarks LLM inference servers manually. We want to automate benchmarking a curated list of models and publish the results on a comparison website.

## Decision

Create a dedicated repo (`llm-grill-platform`) split into independent components, each documented in a sub-ADR:

| ADR | Component | Scope |
|-----|-----------|-------|
| [001a](001a-infra-terraform-scaleway.md) | **Infra** | Terraform + Scaleway, GPU nodes on demand |
| [001b](001b-pipeline-discovery-orchestration.md) | **Pipeline** | Hardcoded model list, CI-triggered benchmarks |
| [001c](001c-data-storage-jsonl.md) | **Storage** (superseded) | Original JSONL-in-Git plan; current impl uses PostgreSQL + S3 `leaderboard.json` |
| [001d](001d-frontend-sveltekit.md) | **Frontend** | Static SvelteKit site — single scatter plot page |
| [001e](001e-error-handling-alerting.md) | **Errors** | Failure classification, orphan sweep, alerting |
| [001f](001f-aggregation-strategy.md) | **Aggregation** | Single Python aggregation, no JS duplication |
| [001g](001g-security-secrets-management.md) | **Security** | Scoped IAM, secret rotation, incident response |

## Architecture

```
llm-grill-platform/
├── .github/workflows/
│   ├── bench.yml            # Triggered on models.yaml push or manual dispatch (001b)
│   └── deploy.yml           # Frontend deploy on new leaderboard.json (001d, future)
├── orchestrator/
│   ├── models.yaml          # Hardcoded model list (source of truth)
│   └── src/                 # FastAPI orchestrator — POST /bench, Terraform, runner
├── infra/                   # Terraform — orchestrator VM + per-run GPU VM (001a)
├── runner/                  # cloud-init + runner.sh executed on each GPU VM
├── site/                    # SvelteKit static site (001d, future)
└── README.md
```

Metrics live in PostgreSQL on the orchestrator VM; the consolidated `leaderboard.json` is published to Scaleway S3 at the end of each bench run (001c superseded, 001f).

## Flow

```
push to models.yaml (or manual dispatch)
  → CI: terraform apply (orchestrator VM) + POST /bench
  → orchestrator: diff models.yaml vs DB
  → for each new/missing model:
      terraform apply → GPU VM
      runner.sh (download + vLLM/llama.cpp + llm-grill)
      runner POSTs /runs/{id}/complete (metrics → Postgres)
      orchestrator: terraform destroy
  → CI: poll GET /bench/status until active=0
  → CI: GET /leaderboard → upload to s3://<bucket>/leaderboard.json
  → CI: terraform destroy (orchestrator VM)
```

## Implementation Order

1. **001c** — Storage (foundation, data format) ✅
2. **001b** — Pipeline (model list, CI) ✅
3. **001a** — Infra (Terraform, setup scripts)
4. **001d** — Frontend (Svelte site)
