<script lang="ts">
	import { onMount } from 'svelte';
	import Header from '$lib/components/Header.svelte';
	import Filters from '$lib/components/Filters.svelte';
	import AxisBar from '$lib/components/AxisBar.svelte';
	import Scatter from '$lib/components/Scatter.svelte';
	import Tooltip from '$lib/components/Tooltip.svelte';
	import Footer from '$lib/components/Footer.svelte';
	import { fetchCatalogs, buildView, engineSub, engineGpu, type Catalogs } from '$lib/data';
	import type { MetricKey } from '$lib/metrics';
	import type { ConcurrencyLevel, ViewRow } from '$lib/types';

	const CATEGORY_ORDER = ['Reasoning', 'MoE', 'Dense', 'Quantized'];
	// Unknown categories sort after the known set (not before, as indexOf -1 would).
	const catRank = (c: string) => {
		const i = CATEGORY_ORDER.indexOf(c);
		return i === -1 ? CATEGORY_ORDER.length : i;
	};

	let catalogs = $state<Catalogs | null>(null);
	let error = $state<string | null>(null);

	let xKey = $state<MetricKey>('tokens_per_sec');
	let yKey = $state<MetricKey>('ttft_mean');
	let concurrency = $state<ConcurrencyLevel>(8);
	let trails = $state(false);

	function setTrails(on: boolean) {
		trails = on;
		// Trails put the ramp level on X (the defining axis of a load curve); X/Y stay
		// freely editable via the selectors afterwards.
		if (on) xKey = 'concurrency';
		// Leaving trails: concurrency is a trailsOnly X axis, so reset to a snapshot default.
		else if (xKey === 'concurrency') xKey = 'tokens_per_sec';
	}
	let activeCats = $state(new Set<string>());
	let activeBrands = $state(new Set<string>());
	let search = $state('');
	let pinned = $state(new Set<string>());
	let hovered = $state<string | null>(null);

	let containerW = $state(1456);
	let chartsEl = $state<HTMLElement | undefined>(undefined);

	onMount(() => {
		fetchCatalogs()
			.then((c) => (catalogs = c))
			.catch((e) => (error = e instanceof Error ? e.message : String(e)));

		const ro = new ResizeObserver((entries) => {
			for (const e of entries) containerW = e.contentRect.width;
		});
		if (chartsEl) ro.observe(chartsEl);
		return () => ro.disconnect();
	});

	const models = $derived(catalogs?.models ?? []);
	const categories = $derived(
		[...new Set(models.flatMap((m) => m.categories))].sort((a, b) => catRank(a) - catRank(b))
	);
	const brands = $derived([...new Set(models.map((m) => m.brand))].sort());

	const view = $derived(
		catalogs ? buildView(catalogs.leaderboard, catalogs.models, concurrency) : []
	);

	function matches(r: ViewRow): boolean {
		if (activeCats.size > 0 && !r.categories.some((c) => activeCats.has(c))) return false;
		if (activeBrands.size > 0 && !activeBrands.has(r.brand)) return false;
		if (search) {
			const q = search.toLowerCase();
			if (!r.name.toLowerCase().includes(q) && !r.model.toLowerCase().includes(q)) return false;
		}
		return true;
	}

	const filtered = $derived(view.filter(matches));
	const totalModels = $derived(new Set(models.map((m) => m.model)).size);
	const visibleModels = $derived(new Set(filtered.map((r) => r.model)).size);

	// Engine columns are driven by engines.json (label + order from the backend Engine
	// enum) — no hardcoded vllm/llamacpp here. Subtitle (GPU/quant) is derived per group
	// from the actual rows, since the backend doesn't know the GPU until runs complete.
	const engineGroups = $derived(
		(catalogs?.engines ?? []).map((e) => {
			const engineRows = view.filter((r) => r.engine === e.id);
			return {
				engine: e.id,
				label: e.label,
				rows: filtered.filter((r) => r.engine === e.id),
				sub: engineSub(engineRows),
				gpu: engineGpu(engineRows)
			};
		})
	);

	// Header stats are fully derived: the backend count and per-engine GPU come from
	// engines.json + observed leaderboard rows, so a new engine/hardware surfaces with
	// no frontend change. GPU is empty until that engine has completed runs.
	const headerEngines = $derived(engineGroups.map((g) => ({ label: g.label, gpu: g.gpu })));

	// One column per engine (capped at 3 so charts stay legible), sized from the
	// observed container width.
	const GAP = 16;
	const cols = $derived(Math.min(Math.max(engineGroups.length, 1), 3));
	const chartW = $derived(Math.floor((containerW - GAP * (cols - 1)) / cols));
	const chartH = $derived(Math.floor(Math.max(360, Math.min(620, chartW * 0.72))));

	// Tooltip(s): the hovered row wins; otherwise show every pinned row so two models
	// can be compared side by side (single-pin gave no comparison before).
	const tooltipRows = $derived(
		(() => {
			if (hovered) {
				const r = filtered.find((x) => x.id === hovered);
				return r ? [r] : [];
			}
			return [...pinned].map((id) => filtered.find((x) => x.id === id)).filter((r): r is ViewRow => !!r);
		})()
	);

	const lastRun = $derived(
		(() => {
			if (!catalogs?.leaderboard.length) return null;
			const max = catalogs.leaderboard
				.map((r) => r.measured_at)
				.sort()
				.at(-1);
			return max ? max.replace('T', ' ').slice(0, 16) + ' UTC' : null;
		})()
	);
	const scenarioLabel = $derived(catalogs?.scenarios[0]?.name ? `scenario: ${catalogs.scenarios[0].name}` : null);

	function toggle(set: Set<string>, v: string): Set<string> {
		const n = new Set(set);
		n.has(v) ? n.delete(v) : n.add(v);
		return n;
	}
	const onToggleCat = (c: string) => (activeCats = toggle(activeCats, c));
	const onToggleBrand = (b: string) => (activeBrands = toggle(activeBrands, b));
	const onPin = (id: string) => (pinned = toggle(pinned, id));
	const concLabel = $derived(concurrency === 'agg' ? 'all' : concurrency);
</script>

<div class="app">
	<Header {totalModels} engines={headerEngines} />

	{#if error}
		<div class="status status-err">failed to load benchmark data — {error}</div>
	{:else if !catalogs}
		<div class="status">loading benchmark data…</div>
	{:else}
		<Filters
			modelsMeta={models}
			{categories}
			{brands}
			{activeCats}
			{activeBrands}
			{search}
			{visibleModels}
			{totalModels}
			pinnedCount={pinned.size}
			{onToggleCat}
			{onToggleBrand}
			onSearch={(v) => (search = v)}
			onClearPins={() => (pinned = new Set())}
		/>

		<AxisBar
			{xKey}
			{yKey}
			{concurrency}
			{trails}
			onX={(k) => (xKey = k)}
			onY={(k) => (yKey = k)}
			onConcurrency={(c) => (concurrency = c)}
			onTrails={setTrails}
		/>

		<section class="charts" bind:this={chartsEl} style="grid-template-columns: repeat({cols}, 1fr)">
			{#each engineGroups as g (g.engine)}
				<div class="chart-card">
					<div class="chart-head">
						<span class="chart-title">{g.label}</span>
						{#if g.sub}<span class="chart-sub">{g.sub}</span>{/if}
						<span class="chart-count">{g.rows.length} pts</span>
					</div>
					<Scatter
						data={g.rows}
						{xKey}
						{yKey}
						{trails}
						width={chartW}
						height={chartH}
						{pinned}
						{hovered}
						onHover={(id) => (hovered = id)}
						{onPin}
						label={trails
							? `${g.label} · load curve`
							: `${g.label} · concurrency = ${concLabel}`}
					/>
				</div>
			{/each}

			{#if tooltipRows.length}
				<div class="tooltip-wrap">
					{#each tooltipRows as row (row.id)}
						<Tooltip {row} {concurrency} />
					{/each}
				</div>
			{/if}
		</section>

		<Footer {lastRun} {scenarioLabel} />
	{/if}
</div>
