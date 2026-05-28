// Data layer: fetch the three public JSON files and merge them into the flat
// ViewRow shape the scatter consumes. Mirrors the mockup's buildView(), adapted
// to the real (flat) leaderboard rows produced by storage.update_leaderboard_for.
import type {
	ConcurrencyLevel,
	ConcurrencyPoint,
	EngineMeta,
	Hardware,
	LeaderboardRow,
	ModelMeta,
	Scenario,
	ViewRow
} from './types';

// In prod, VITE_DATA_BASE_URL points at the S3 bucket root. In dev with no env,
// fall back to bundled fixtures under static/sample/.
const BASE = import.meta.env.VITE_DATA_BASE_URL ?? '/sample';

export interface Catalogs {
	leaderboard: LeaderboardRow[];
	models: ModelMeta[];
	scenarios: Scenario[];
	engines: EngineMeta[];
}

async function getJson<T>(file: string): Promise<T> {
	const res = await fetch(`${BASE}/${file}`);
	if (!res.ok) throw new Error(`${file}: ${res.status} ${res.statusText}`);
	return (await res.json()) as T;
}

/** Tolerant fetch for non-essential catalogs: a missing/unavailable file degrades to
 *  `fallback` instead of failing the whole page load. */
async function getJsonOptional<T>(file: string, fallback: T): Promise<T> {
	try {
		return await getJson<T>(file);
	} catch {
		return fallback;
	}
}

/** Engines derived from the leaderboard when engines.json is unavailable: distinct
 *  engine ids in first-seen order, labelled by their raw id (no curated display name). */
function enginesFromLeaderboard(leaderboard: LeaderboardRow[]): EngineMeta[] {
	const ids = [...new Set(leaderboard.map((r) => r.engine))];
	return ids.map((id) => ({ id, label: id }));
}

export async function fetchCatalogs(): Promise<Catalogs> {
	// leaderboard + models are essential — a failure here is a real page-load error.
	const [leaderboard, models] = await Promise.all([
		getJson<LeaderboardRow[]>('leaderboard.json'),
		getJson<ModelMeta[]>('models.json')
	]);
	// engines + scenarios are decorative/ordering aids: degrade gracefully so the
	// dashboard stays usable with partial data.
	const [scenarios, engines] = await Promise.all([
		getJsonOptional<Scenario[]>('scenarios.json', []),
		getJsonOptional<EngineMeta[]>('engines.json', [])
	]);
	return {
		leaderboard,
		models,
		scenarios,
		engines: engines.length ? engines : enginesFromLeaderboard(leaderboard)
	};
}

function hardwareFor(gpuType: string): Hardware {
	return { label: `1×${gpuType}`, type: gpuType };
}

/** Synthesize a point from the row's flat top-level aggregate metrics. */
function aggregatePoint(row: LeaderboardRow): ConcurrencyPoint {
	return {
		concurrency: 0,
		n_requests: row.n_requests,
		success_rate: row.success_rate,
		ttft_mean_s: row.ttft_mean_s,
		ttft_median_s: row.ttft_median_s,
		ttft_p95_s: row.ttft_p95_s,
		tpot_mean_s: row.tpot_mean_s,
		e2e_mean_s: row.e2e_mean_s,
		e2e_p95_s: row.e2e_p95_s,
		tokens_per_second_mean: row.tokens_per_second_mean,
		total_tokens_per_second: row.total_tokens_per_second,
		requests_per_second: row.requests_per_second
	};
}

/** Per-concurrency points for a row — tolerates an old/missing field. */
export function perConcurrency(row: LeaderboardRow): ConcurrencyPoint[] {
	return row.per_concurrency ?? [];
}

/** The ConcurrencyPoint to show for a row at a given level (agg → flat aggregate). */
export function pointAt(row: LeaderboardRow, level: ConcurrencyLevel): ConcurrencyPoint {
	if (level === 'agg') return aggregatePoint(row);
	return perConcurrency(row).find((p) => p.concurrency === level) ?? aggregatePoint(row);
}

/** Map a point (seconds-based) onto the scatter's flat keys (latencies in ms). */
export function flattenPoint(p: ConcurrencyPoint) {
	return {
		concurrency: p.concurrency,
		ttft_mean: Math.round(p.ttft_mean_s * 1000),
		ttft_p95: Math.round(p.ttft_p95_s * 1000),
		ttft_p50: Math.round(p.ttft_median_s * 1000),
		tpot_mean: +(p.tpot_mean_s * 1000).toFixed(2),
		e2e_mean: Math.round(p.e2e_mean_s * 1000),
		e2e_p95: Math.round(p.e2e_p95_s * 1000),
		tokens_per_sec: p.tokens_per_second_mean,
		total_tokens_per_sec: p.total_tokens_per_second,
		requests_per_sec: p.requests_per_second,
		success_rate: p.success_rate,
		n_requests: p.n_requests
	};
}

function metaKey(model: string, engine: string): string {
	return `${model}@${engine}`;
}

/** Merge leaderboard + models into ViewRows at a given concurrency level. */
export function buildView(
	leaderboard: LeaderboardRow[],
	models: ModelMeta[],
	level: ConcurrencyLevel
): ViewRow[] {
	const byKey = new Map(models.map((m) => [metaKey(m.model, m.engine), m]));
	return leaderboard.map((row) => {
		const meta = byKey.get(metaKey(row.model, row.engine));
		const flat = flattenPoint(pointAt(row, level));
		return {
			id: metaKey(row.model, row.engine),
			model: row.model,
			engine: row.engine,
			name: meta?.display_name ?? row.model.split('/').pop() ?? row.model,
			brand: meta?.brand ?? row.model.split('/')[0],
			params: meta?.params_b ?? 0,
			params_b: meta?.params_b ?? 0,
			categories: meta?.categories ?? [],
			quantization: meta?.quantization ?? null,
			hardware: hardwareFor(row.gpu_type),
			_row: row,
			_meta: meta,
			...flat
		};
	});
}

/** GPU summary for an engine's rows, derived (never hardcoded): a single type when
 *  uniform (e.g. "H100"), "N GPU types" when mixed, or "" when no runs landed yet. */
export function engineGpu(rows: ViewRow[]): string {
	const gpus = [...new Set(rows.map((r) => r.hardware.type).filter(Boolean))];
	return gpus.length === 1 ? gpus[0] : gpus.length > 1 ? `${gpus.length} GPU types` : '';
}

/** Subtitle for an engine column, derived from its rows (no hardcoded GPU/quant).
 *  e.g. "1×L40S · Q4_K_M", "1×H100", or "" when nothing is known. */
export function engineSub(rows: ViewRow[]): string {
	const gpu = engineGpu(rows);
	const quants = [...new Set(rows.map((r) => r.quantization).filter((q): q is string => !!q))];
	const gpuPart = gpu && !gpu.includes('types') ? `1×${gpu}` : gpu;
	const quantPart = quants.length === 1 ? quants[0] : '';
	return [gpuPart, quantPart].filter(Boolean).join(' · ');
}
