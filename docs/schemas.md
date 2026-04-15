# Aggregated JSON Schema Contract

The three files under `results/aggregated/` are the frontend's only data source. The site build copies them to `static/data/` with no further computation.

## Conventions

- All metrics are computed over rows where `success = true`, except `success_rate` and `n_requests` which use all rows.
- Latencies in **ms**, throughput in **tok/s**, `success_rate` as a ratio in `[0, 1]`.
- `p95` = 95th percentile.
- `slug` = HuggingFace ID with `/` replaced by `--`.
- `date` = `YYYY-MM-DD`.
- If a metric cannot be computed (e.g. all rows failed), the value is `null`.
- A `(model, backend)` pair is simply absent from all three files when no data exists.

## `leaderboard.json`

One entry per `(model, backend)` for the **latest run**.

```ts
type Leaderboard = LeaderboardEntry[];

type LeaderboardEntry = {
  model: string;           // HF ID with "/"
  backend: "vllm" | "llamacpp";
  date: string;            // YYYY-MM-DD
  ttft_mean: number | null;
  ttft_p95: number | null;
  tpot_mean: number | null;
  e2e_mean: number | null;
  tokens_per_sec: number | null;
  success_rate: number;    // count(success) / count(all)
  n_requests: number;      // total rows
};
```

## `models/{slug}.json`

Full history for a single model, broken down by conversation.

```ts
type ModelDetail = {
  model: string;
  runs: Array<{
    date: string;
    backend: "vllm" | "llamacpp";
    metrics: RunMetrics;                     // aggregate over all conversations
    conversations: Array<{
      name: "short-qa" | "coding" | "multi-turn" | "long-context";
      metrics: RunMetrics;                   // same fields, filtered to this conversation
    }>;
  }>;
};

type RunMetrics = {
  ttft_mean: number | null;
  ttft_p95: number | null;
  tpot_mean: number | null;
  e2e_mean: number | null;
  tokens_per_sec: number | null;
  success_rate: number;
  n_requests: number;
};
```

## `history.json`

Time series for trend charts.

```ts
type History = {
  series: Array<{
    model: string;
    backend: "vllm" | "llamacpp";
    points: Array<{
      date: string;
      ttft_mean: number | null;
      tokens_per_sec: number | null;
    }>;                                      // sorted ascending by date
  }>;
};
```
