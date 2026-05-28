// Shapes of the three public JSON files the orchestrator publishes to S3.
// See orchestrator CLAUDE.md § "Public S3 artifacts" and docs/frontend-plan.md.

/** One ramp level inside a leaderboard row's `per_concurrency`. */
export interface ConcurrencyPoint {
	concurrency: number;
	n_requests: number;
	success_rate: number;
	ttft_mean_s: number;
	ttft_median_s: number;
	ttft_p95_s: number;
	tpot_mean_s: number;
	e2e_mean_s: number;
	e2e_p95_s: number;
	tokens_per_second_mean: number;
	total_tokens_per_second: number;
	requests_per_second: number;
}

/** A row of leaderboard.json — one per benched (model, engine). Flat metrics. */
export interface LeaderboardRow {
	model: string;
	engine: string;
	gpu_type: string;
	tokens_per_second_mean: number;
	total_tokens_per_second: number;
	requests_per_second: number;
	n_requests: number;
	ttft_mean_s: number;
	ttft_median_s: number;
	ttft_p95_s: number;
	tpot_mean_s: number;
	e2e_mean_s: number;
	e2e_p95_s: number;
	success_rate: number;
	// Optional: pre-extension leaderboard rows on S3 may lack this entirely.
	per_concurrency?: ConcurrencyPoint[];
	run_id: string;
	measured_at: string;
}

/** A row of models.json — derived editorial metadata, keyed by (model, engine). */
export interface ModelMeta {
	model: string;
	engine: string;
	display_name: string;
	brand: string;
	params_b: number;
	quantization: string | null;
	categories: string[];
	scenario: string;
}

/** A row of scenarios.json — the load shape of one scenario YAML. */
export interface Scenario {
	path: string;
	name: string;
	description: string;
	concurrency_levels: number[];
	iterations: number | null;
	max_tokens: number | null;
	prompt: string | null;
}

/** Hardware label derived from a row's gpu_type (no hardware object on S3). */
export interface Hardware {
	label: string;
	type: string;
}

/** Flattened row consumed by the scatter — metrics in the units the chart expects
 *  (latencies in ms), merged with model metadata. `_row`/`_point` keep the raw
 *  source for the tooltip and concurrency trails. */
export interface ViewRow {
	id: string;
	model: string;
	engine: string;
	name: string;
	brand: string;
	params: number;
	categories: string[];
	quantization: string | null;
	hardware: Hardware;
	concurrency: number;
	ttft_mean: number;
	ttft_p95: number;
	ttft_p50: number;
	tpot_mean: number;
	e2e_mean: number;
	e2e_p95: number;
	tokens_per_sec: number;
	total_tokens_per_sec: number;
	requests_per_sec: number;
	success_rate: number;
	n_requests: number;
	params_b: number;
	_row: LeaderboardRow;
	_meta: ModelMeta | undefined;
}

/** Either "agg" (the row's flat aggregate) or a numeric ramp level. */
export type ConcurrencyLevel = 'agg' | number;

/** A row of engines.json — id + display label, ordered by the backend Engine enum. */
export interface EngineMeta {
	id: string;
	label: string;
}
