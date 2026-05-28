import { describe, expect, it } from 'vitest';
import { buildView, engineSub, flattenPoint, pointAt } from '../src/lib/data';
import type { ConcurrencyPoint, LeaderboardRow, ModelMeta, ViewRow } from '../src/lib/types';

function point(over: Partial<ConcurrencyPoint> = {}): ConcurrencyPoint {
	return {
		concurrency: 8,
		n_requests: 16,
		success_rate: 1,
		ttft_mean_s: 0.044,
		ttft_median_s: 0.04,
		ttft_p95_s: 0.06,
		tpot_mean_s: 0.0137,
		e2e_mean_s: 1.1,
		e2e_p95_s: 1.2,
		tokens_per_second_mean: 71.3,
		total_tokens_per_second: 136.3,
		requests_per_second: 1.25,
		...over
	};
}

function row(over: Partial<LeaderboardRow> = {}): LeaderboardRow {
	return {
		model: 'Qwen/Qwen2.5-14B-Instruct',
		engine: 'vllm',
		gpu_type: 'H100',
		tokens_per_second_mean: 13.08,
		total_tokens_per_second: 136.31,
		requests_per_second: 1.25,
		n_requests: 384,
		ttft_mean_s: 9.2,
		ttft_median_s: 6.1,
		ttft_p95_s: 28.77,
		tpot_mean_s: 0.0172,
		e2e_mean_s: 11.3,
		e2e_p95_s: 30.61,
		success_rate: 1,
		per_concurrency: [point({ concurrency: 1 }), point({ concurrency: 8 })],
		run_id: 'r1',
		measured_at: '2026-05-22T14:22:00Z',
		...over
	};
}

const meta = (over: Partial<ModelMeta> = {}): ModelMeta => ({
	model: 'Qwen/Qwen2.5-14B-Instruct',
	engine: 'vllm',
	display_name: 'Qwen 2.5 14B',
	brand: 'Qwen',
	params_b: 14,
	quantization: null,
	categories: ['Dense'],
	scenario: 'scenarios/ramp.yaml',
	...over
});

describe('flattenPoint', () => {
	it('converts second-based latencies to milliseconds', () => {
		const f = flattenPoint(point({ ttft_mean_s: 0.044, ttft_p95_s: 0.06, ttft_median_s: 0.04 }));
		// Given seconds in the source, When flattened, Then latencies are ms-rounded.
		expect(f.ttft_mean).toBe(44);
		expect(f.ttft_p95).toBe(60);
		expect(f.ttft_p50).toBe(40);
		expect(f.tpot_mean).toBeCloseTo(13.7, 5);
	});

	it('passes throughput fields through untouched', () => {
		const f = flattenPoint(point({ tokens_per_second_mean: 71.3, total_tokens_per_second: 136.3 }));
		expect(f.tokens_per_sec).toBe(71.3);
		expect(f.total_tokens_per_sec).toBe(136.3);
	});
});

describe('pointAt', () => {
	it('returns the row aggregate for "agg"', () => {
		// Given a row, When level is agg, Then the flat top-level metrics are used.
		const pt = pointAt(row({ ttft_mean_s: 9.2 }), 'agg');
		expect(pt.ttft_mean_s).toBe(9.2);
		expect(pt.concurrency).toBe(0);
	});

	it('returns the matching ramp level when present', () => {
		const pt = pointAt(row(), 8);
		expect(pt.concurrency).toBe(8);
	});

	it('falls back to the aggregate when the level is absent', () => {
		// Given a level not in per_concurrency, When pointAt, Then aggregate (concurrency 0).
		const pt = pointAt(row(), 64);
		expect(pt.concurrency).toBe(0);
	});

	it('tolerates rows missing per_concurrency entirely', () => {
		const pt = pointAt(row({ per_concurrency: undefined }), 8);
		expect(pt.concurrency).toBe(0);
	});
});

describe('buildView', () => {
	it('merges model metadata on (model, engine)', () => {
		const [v] = buildView([row()], [meta()], 'agg') as ViewRow[];
		expect(v.name).toBe('Qwen 2.5 14B');
		expect(v.brand).toBe('Qwen');
		expect(v.params_b).toBe(14);
		expect(v.categories).toEqual(['Dense']);
		expect(v.id).toBe('Qwen/Qwen2.5-14B-Instruct@vllm');
	});

	it('falls back to derived name/brand when no metadata matches', () => {
		// Given a leaderboard row with no models.json entry, When built, Then graceful defaults.
		const [v] = buildView([row()], [], 'agg');
		expect(v.name).toBe('Qwen2.5-14B-Instruct');
		expect(v.brand).toBe('Qwen');
		expect(v.params_b).toBe(0);
		expect(v.categories).toEqual([]);
	});

	it('does not cross-join engines (vllm meta must not decorate a llamacpp row)', () => {
		const [v] = buildView([row({ engine: 'llamacpp' })], [meta({ engine: 'vllm' })], 'agg');
		expect(v.name).toBe('Qwen2.5-14B-Instruct'); // fell back, no wrong-engine merge
	});
});

describe('engineSub', () => {
	const vr = (over: Partial<ViewRow>): ViewRow =>
		({ hardware: { label: '', type: 'L40S' }, quantization: null, ...over }) as ViewRow;

	it('shows a single GPU type', () => {
		expect(engineSub([vr({}), vr({})])).toBe('1×L40S');
	});

	it('appends a shared quantization', () => {
		expect(engineSub([vr({ quantization: 'Q4_K_M' }), vr({ quantization: 'Q4_K_M' })])).toBe(
			'1×L40S · Q4_K_M'
		);
	});

	it('summarises mixed GPU types instead of lying', () => {
		const h100 = vr({ hardware: { label: '', type: 'H100' } });
		expect(engineSub([vr({}), h100])).toBe('2 GPU types');
	});

	it('returns empty string when nothing is known', () => {
		expect(engineSub([])).toBe('');
	});
});
