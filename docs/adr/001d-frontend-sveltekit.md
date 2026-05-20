# ADR 001d: Frontend — Static SvelteKit Site

**Date:** 2026-03-25
**Status:** Validated
**Parent:** [ADR 001](001-automated-benchmark-site.md)

---

## Context

Benchmark results (JSONL) must be presented on a website supporting:
- Backend comparison for a given model
- Sortable leaderboard by metric
- Run history to track performance over time
- No backend server — static site only

## Options Considered

| Option | Description | Verdict |
|--------|-------------|---------|
| **A. SvelteKit + adapter-static** | Static site rebuilt on each results push. Pre-aggregated JSON consumed at build time | **Chosen** |
| B. Next.js (React) | More mature ecosystem | Rejected: heavier and more verbose for a simple dashboard |
| C. Streamlit / Gradio | All Python, quick prototype | Rejected: requires a server, less UX control, no SEO |

## Decision

**Option A**: SvelteKit with adapter-static.

## Design

### Structure

```
site/
├── scripts/
│   └── build-data.js            # Copies pre-aggregated JSON to static/data/
├── src/
│   ├── lib/
│   │   ├── types.ts
│   │   ├── utils.ts
│   │   └── components/          # MetricsTable, ComparisonChart, TimeSeriesChart
│   └── routes/
│       ├── +page.svelte         # Leaderboard
│       ├── model/[slug]/        # Model detail (all backends compared)
│       └── history/             # Performance evolution over time
└── static/data/                 # Generated (gitignored)
```

### Pages

**Leaderboard (`/`)**: sortable table of all (model × backend), latest run. Columns: TTFT mean/p95, TPOT mean, E2E mean, tokens/s, success %. Filters by model size, date, backend.

**Model detail (`/model/[slug]`)**: comparison of all backends for a given model. Bar charts (TTFT, throughput per backend), KV cache and GPU metrics.

**History (`/history`)**: line charts showing performance evolution per (model, backend) over time. Useful for detecting regressions between backend versions.

### Charting

LayerCake (Svelte-native, lightweight). Fallback: Chart.js via `svelte-chartjs` if more chart types are needed.

### Deployment

GitHub Actions (`deploy.yml`): triggered after the `bench` workflow uploads a new `leaderboard.json` to S3 (manual trigger or post-bench hook). Builds SvelteKit, deploys to GitHub Pages; the page fetches `leaderboard.json` from S3 at runtime (or bakes it at build time — see `docs/frontend-plan.md`).

## Consequences

| | |
|---|---|
| **+** | Zero server infra (GitHub Pages), instant client-side loading (pre-aggregated data), lightweight bundle, automatic rebuild on new results |
| **−** | No full-text search or ad-hoc queries. Build time grows with data volume (mitigation: incremental aggregation) |
