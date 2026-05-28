// Metric catalog for the axis selectors + shared formatters.
// Ported from the mockup's data.js, minus tpot_p95 / e2e_p50 which the backend
// (llm_grill AggregatedMetrics) does not expose.

/** Numeric axis keys — all present on ViewRow as numbers, so indexing is safe. */
export type MetricKey =
	| 'concurrency'
	| 'ttft_mean'
	| 'ttft_p95'
	| 'ttft_p50'
	| 'tpot_mean'
	| 'e2e_mean'
	| 'e2e_p95'
	| 'tokens_per_sec'
	| 'total_tokens_per_sec'
	| 'success_rate'
	| 'n_requests'
	| 'params_b';

export interface Metric {
	key: MetricKey;
	label: string;
	unit: string;
	lowerIsBetter: boolean;
	/** Only meaningful as a trail-mode X axis (the ramp level itself). */
	trailsOnly?: boolean;
}

export const METRICS: Metric[] = [
	{ key: 'concurrency', label: 'Concurrency', unit: 'users', lowerIsBetter: false, trailsOnly: true },
	{ key: 'ttft_mean', label: 'TTFT mean', unit: 'ms', lowerIsBetter: true },
	{ key: 'ttft_p95', label: 'TTFT p95', unit: 'ms', lowerIsBetter: true },
	{ key: 'ttft_p50', label: 'TTFT p50', unit: 'ms', lowerIsBetter: true },
	{ key: 'tpot_mean', label: 'TPOT mean', unit: 'ms/tok', lowerIsBetter: true },
	{ key: 'e2e_mean', label: 'E2E mean', unit: 'ms', lowerIsBetter: true },
	{ key: 'e2e_p95', label: 'E2E p95', unit: 'ms', lowerIsBetter: true },
	{ key: 'tokens_per_sec', label: 'Throughput', unit: 'tok/s', lowerIsBetter: false },
	{ key: 'total_tokens_per_sec', label: 'Total throughput', unit: 'tok/s', lowerIsBetter: false },
	{ key: 'success_rate', label: 'Success rate', unit: '', lowerIsBetter: false },
	{ key: 'n_requests', label: 'Requests', unit: '', lowerIsBetter: false },
	{ key: 'params_b', label: 'Parameters', unit: 'B', lowerIsBetter: false }
];

export const SELECTABLE_METRICS = METRICS.filter((m) => !m.trailsOnly);

export const CONCURRENCY_LEVELS = [1, 4, 8, 16, 32, 64];

/** Latency formatter: sub-second in ms, else seconds. */
export function fmtMs(seconds: number): string {
	return seconds < 1 ? `${(seconds * 1000).toFixed(0)} ms` : `${seconds.toFixed(2)} s`;
}

/** Axis tick formatter (values already in the row's display units).
 *  Latencies stay in ms end-to-end (matching the metric `unit` and flattenPoint),
 *  so large values collapse to the generic "k" suffix rather than a stray "s". */
export function formatTick(v: number, key: string): string {
	if (key === 'success_rate') return `${(v * 100).toFixed(0)}%`;
	if (Math.abs(v) >= 1000) return `${(v / 1000).toFixed(1)}k`;
	if (Number.isInteger(v) || Math.abs(v) >= 10) return v.toFixed(0);
	return v.toFixed(1);
}
