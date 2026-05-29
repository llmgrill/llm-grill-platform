<script lang="ts">
	import { METRICS, SELECTABLE_METRICS, CONCURRENCY_LEVELS, type MetricKey } from '$lib/metrics';
	import type { ConcurrencyLevel } from '$lib/types';

	let {
		xKey,
		yKey,
		concurrency,
		trails,
		onX,
		onY,
		onConcurrency,
		onTrails
	}: {
		xKey: MetricKey;
		yKey: MetricKey;
		concurrency: ConcurrencyLevel;
		trails: boolean;
		onX: (k: MetricKey) => void;
		onY: (k: MetricKey) => void;
		onConcurrency: (c: ConcurrencyLevel) => void;
		onTrails: (on: boolean) => void;
	} = $props();

	const levels: ConcurrencyLevel[] = ['agg', ...CONCURRENCY_LEVELS];
	// In trails mode the X axis can be the ramp level itself (concurrency), so the
	// trailsOnly metrics become selectable.
	const axisMetrics = $derived(trails ? METRICS : SELECTABLE_METRICS);
</script>

<section class="axes">
	<label class="axis-select">
		<span class="axis-label">X</span>
		<select value={xKey} onchange={(e) => onX(e.currentTarget.value as MetricKey)}>
			{#each axisMetrics as m (m.key)}
				<option value={m.key}>{m.label}</option>
			{/each}
		</select>
		<svg width="10" height="10" viewBox="0 0 10 10" class="axis-chev"
			><path d="M2 4l3 3 3-3" stroke="currentColor" fill="none" stroke-width="1.2" /></svg
		>
	</label>

	<label class="axis-select">
		<span class="axis-label">Y</span>
		<select value={yKey} onchange={(e) => onY(e.currentTarget.value as MetricKey)}>
			{#each axisMetrics as m (m.key)}
				<option value={m.key}>{m.label}</option>
			{/each}
		</select>
		<svg width="10" height="10" viewBox="0 0 10 10" class="axis-chev"
			><path d="M2 4l3 3 3-3" stroke="currentColor" fill="none" stroke-width="1.2" /></svg
		>
	</label>

	<div class="conc-select" title="Snapshot = one ramp level per point; Trails = the load curve per model">
		<span class="axis-label">Mode</span>
		<div class="conc-track">
			<button class="conc-btn" class:conc-on={!trails} onclick={() => onTrails(false)}>snapshot</button>
			<button class="conc-btn" class:conc-on={trails} onclick={() => onTrails(true)}>trails</button>
		</div>
	</div>

	{#if !trails}
		<div class="conc-select" title="Pick the concurrency level to display">
			<span class="axis-label">Concurrency</span>
			<div class="conc-track">
				{#each levels as l (l)}
					<button class="conc-btn" class:conc-on={concurrency === l} onclick={() => onConcurrency(l)}>
						{l === 'agg' ? 'all' : l}
					</button>
				{/each}
			</div>
		</div>
	{/if}

	<div class="encoding">
		{#if !trails}
			<span class="enc-item">
				<span class="enc-swatch">
					<span class="enc-circle sm"></span>
					<span class="enc-circle md"></span>
					<span class="enc-circle lg"></span>
				</span>
				<span class="enc-label">size = params</span>
			</span>
		{:else}
			<span class="enc-item">
				<span class="enc-gradient"></span>
				<span class="enc-label">color = success</span>
			</span>
		{/if}
	</div>
</section>
