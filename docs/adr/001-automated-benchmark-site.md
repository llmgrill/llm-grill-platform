# ADR 001: Automated LLM Benchmark Site

**Date:** 2026-03-21
**Status:** Proposed
**Deciders:** Gireg Roussel

---

## Context

The `llm-grill` CLI benchmarks LLM inference servers manually. We want to automate the full loop:

1. **Discover** new models nightly from HuggingFace Hub.
2. **Benchmark** them on 2 backends (vLLM for raw GPU perf, llama.cpp for quantized GGUF) on H100 GPUs.
3. **Publish** results on a comparison website (leaderboard, per-model detail, history).

## Decision

Create a dedicated repo (`llm-grill-nightly`) split into independent components, each documented in a sub-ADR:

| ADR | Component | Scope |
|-----|-----------|-------|
| [001a](001a-infra-terraform-scaleway.md) | **Infra** | Terraform + Scaleway, up to 2 parallel H100s |
| [001b](001b-pipeline-discovery-orchestration.md) | **Pipeline** | HF discovery, dedup, orchestration, GitHub Actions |
| [001c](001c-data-storage-jsonl.md) | **Storage** | JSONL format, `results/` layout, dedup |
| [001d](001d-frontend-sveltekit.md) | **Frontend** | Static SvelteKit site |
| [001e](001e-error-handling-alerting.md) | **Errors** | Failure classification, orphan sweep, alerting |
| [001f](001f-aggregation-strategy.md) | **Aggregation** | Single Python aggregation, no JS duplication |
| [001g](001g-security-secrets-management.md) | **Security** | Scoped IAM, secret rotation, incident response |

## Architecture

```
llm-grill-nightly/
├── .github/workflows/
│   ├── nightly.yml          # Cron → full pipeline (001b)
│   └── deploy.yml           # Rebuild site on results/ push (001d)
├── infra/                   # Terraform Scaleway (001a)
├── pipeline/                # Python orchestration scripts (001b)
├── results/                 # Raw JSONL + aggregated JSON (001c, 001f)
├── site/                    # SvelteKit static site (001d)
└── README.md
```

## Flow

```
discover.py → check_existing.py →
  for each model:
    terraform apply (1 H100 per backend, in parallel)
    llm-grill run (on each machine)
    collect JSONL results
    terraform destroy
  aggregate.py → aggregated JSON
  git commit + push results/
  → automatic site rebuild
```

## Implementation Order

1. **001c** — Storage (foundation, data format)
2. **001b** — Pipeline (discovery, orchestration)
3. **001a** — Infra (Terraform, setup scripts)
4. **001d** — Frontend (Svelte site)
