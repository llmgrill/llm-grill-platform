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

GitHub Actions: triggered after the `bench` workflow uploads a new `leaderboard.json` to S3 (or on `site/**` push). Builds SvelteKit; the page fetches `leaderboard.json` from S3 at runtime. **Superseded — see § Revision below** (deployment moved to Cloudflare Pages).

## Consequences

| | |
|---|---|
| **+** | Zero server infra, instant client-side loading (pre-aggregated data), lightweight bundle, automatic rebuild on new results |
| **−** | No full-text search or ad-hoc queries. Build time grows with data volume (mitigation: incremental aggregation) |

## Revision — 2026-05-26 (MVP build from Claude Design mockup)

Two decisions from the original ADR were superseded while implementing the
single-page scatter dashboard (`site/`). The SvelteKit + adapter-static base holds.

- **Charting: native Svelte SVG + `d3-scale`, not LayerCake.** The mockup's scatter
  is hand-rolled SVG with bespoke features (concurrency trails, dual-engine overlay
  pairing, hover/pin dimming, in-SVG labels). LayerCake supplies scales + a responsive
  container but we'd still author every mark by hand — it would add a dependency and an
  abstraction without removing the real work. `d3-scale` covers linear scales + nice
  ticks; the rest is Svelte SVG (≈1:1 port of the React components).
- **Deployment: Cloudflare Pages, not GitHub Pages.** `wrangler pages deploy build`
  from `.github/workflows/deploy-site.yml`, triggered on `site/**` pushes and on a
  successful `bench` run. Data is fetched at runtime from the public S3 JSON
  (`VITE_DATA_BASE_URL`).
- **No Tailwind.** The mockup is plain CSS driven by custom properties; ported verbatim
  into `src/app.css` (tokens) + scoped component styles.
- **MVP exposes minimal controls** (theme toggle only); layout is fixed to split and
  concurrency trails / overlay are implemented but not surfaced — re-exposable later.
