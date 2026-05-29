<script lang="ts">
	import { flattenPoint, perConcurrency } from '$lib/data';
	import { METRICS, formatTick, type MetricKey } from '$lib/metrics';
	import { paddedDomain, linear, ticksFor, colorScale, radius } from '$lib/scales';
	import type { ViewRow } from '$lib/types';

	let {
		data,
		xKey,
		yKey,
		sizeKey = 'params_b',
		width,
		height,
		pinned,
		hovered,
		onHover,
		onPin,
		showGrid = true,
		label = '',
		trails = false
	}: {
		data: ViewRow[];
		xKey: MetricKey;
		yKey: MetricKey;
		sizeKey?: MetricKey;
		width: number;
		height: number;
		pinned: Set<string>;
		hovered: string | null;
		onHover: (id: string | null) => void;
		onPin: (id: string) => void;
		showGrid?: boolean;
		label?: string;
		trails?: boolean;
	} = $props();

	const padding = { top: 14, right: 18, bottom: 38, left: 52 };
	const iw = $derived(width - padding.left - padding.right);
	const ih = $derived(height - padding.top - padding.bottom);

	const val = (d: ViewRow, key: MetricKey): number => d[key];

	const xMetric = $derived(METRICS.find((m) => m.key === xKey));
	const yMetric = $derived(METRICS.find((m) => m.key === yKey));

	// Points feeding the domain (include trail points when trails are on).
	const allPoints = $derived(
		(() => {
			const out = data.map((d) => ({ x: val(d, xKey), y: val(d, yKey), s: val(d, sizeKey) }));
			if (trails) {
				for (const d of data) {
					for (const pc of perConcurrency(d._row)) {
						const m = flattenPoint(pc) as Record<string, number>;
						out.push({ x: m[xKey], y: m[yKey], s: m[sizeKey] ?? 0 });
					}
				}
			}
			return out;
		})()
	);

	const xDomain = $derived(paddedDomain(allPoints.map((p) => p.x)));
	const yDomain = $derived(paddedDomain(allPoints.map((p) => p.y)));
	const sizes = $derived(allPoints.map((p) => p.s));
	const sMin = $derived(Math.min(...sizes));
	const sMax = $derived(Math.max(...sizes));

	const xScale = $derived(linear(xDomain, [padding.left, padding.left + iw]));
	const yScale = $derived(linear(yDomain, [padding.top + ih, padding.top]));
	const xTicks = $derived(ticksFor(xDomain, 5));
	const yTicks = $derived(ticksFor(yDomain, 5));

	// Skip points whose chosen axes are missing/non-finite (e.g. old leaderboard
	// rows lacking a metric) so we never emit NaN SVG coordinates.
	const points = $derived(
		data.filter(
			(d) =>
				Number.isFinite(val(d, xKey)) && Number.isFinite(val(d, yKey))
		)
	);

	// Nothing to draw: no rows, or rows whose chosen axes are all unplottable
	// (e.g. legacy leaderboard rows missing the selected metric). In trails mode
	// the curve points carry the chart, so fall back to the full point set.
	const noMarks = $derived(trails ? allPoints.length === 0 : points.length === 0);

	const r = (d: ViewRow) => radius(val(d, sizeKey), sMin, sMax);
	const isActive = (id: string) => hovered === id || pinned.has(id);
	const isDim = (id: string) => (pinned.size > 0 || hovered != null) && !isActive(id);

	// Precompute screen-space trail geometry once per row (path + points), instead
	// of recomputing it for the path, every circle, and the label on each render.
	const trailData = $derived(
		trails
			? data.map((d) => {
					const pts = perConcurrency(d._row).map(
						(pc) => {
							const m = flattenPoint(pc) as Record<string, number>;
							return [xScale(m[xKey]), yScale(m[yKey])] as [number, number];
						}
					);
					const path = pts
						.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0].toFixed(1)} ${p[1].toFixed(1)}`)
						.join(' ');
					return { d, pts, path };
				})
			: []
	);

	// Keyboard equivalent of click-to-pin, so the chart is reachable without a mouse.
	function onKey(e: KeyboardEvent, id: string) {
		if (e.key === 'Enter' || e.key === ' ') {
			e.preventDefault();
			onPin(id);
		}
	}
</script>

{#if noMarks}
	<div class="status" style="min-height:{height}px">no runs for this view yet</div>
{:else}
	<svg {width} {height} style="display:block">
	<text x={padding.left} y={padding.top - 2} fill="var(--text-3)" font-size="10" font-family="var(--mono)">{label}</text>

	{#if showGrid}
		{#each yTicks as t, i (i)}
			<line x1={padding.left} x2={width - padding.right} y1={yScale(t)} y2={yScale(t)} stroke="var(--grid)" />
		{/each}
		{#each xTicks as t, i (i)}
			<line y1={padding.top} y2={height - padding.bottom} x1={xScale(t)} x2={xScale(t)} stroke="var(--grid)" />
		{/each}
	{/if}

	{#each yTicks as t, i (i)}
		<text x={padding.left - 8} y={yScale(t) + 3} fill="var(--text-3)" font-size="10" font-family="var(--mono)" text-anchor="end">{formatTick(t, yKey)}</text>
	{/each}
	{#each xTicks as t, i (i)}
		<text x={xScale(t)} y={height - padding.bottom + 14} fill="var(--text-3)" font-size="10" font-family="var(--mono)" text-anchor="middle">{formatTick(t, xKey)}</text>
	{/each}

	<line x1={padding.left} x2={padding.left} y1={padding.top} y2={height - padding.bottom} stroke="var(--axis)" />
	<line x1={padding.left} x2={width - padding.right} y1={height - padding.bottom} y2={height - padding.bottom} stroke="var(--axis)" />

	<text x={padding.left + iw / 2} y={height - 6} fill="var(--text-2)" font-size="11" text-anchor="middle">
		{xMetric?.label}
		{#if xMetric?.unit}<tspan fill="var(--text-4)" font-family="var(--mono)" font-size="10">({xMetric.unit})</tspan>{/if}
	</text>
	<text transform={`rotate(-90 14 ${padding.top + ih / 2})`} x={14} y={padding.top + ih / 2} fill="var(--text-2)" font-size="11" text-anchor="middle">
		{yMetric?.label}
		{#if yMetric?.unit}<tspan fill="var(--text-4)" font-family="var(--mono)" font-size="10">({yMetric.unit})</tspan>{/if}
	</text>

	{#if trails}
		<g>
			{#each trailData as { d, pts, path } (d.id)}
				<g
					style="opacity:{isDim(d.id) ? 0.06 : isActive(d.id) ? 1 : 0.35};transition:opacity 120ms;cursor:pointer"
					role="button"
					tabindex="0"
					aria-label={d.name}
					onmouseenter={() => onHover(d.id)}
					onmouseleave={() => onHover(null)}
					onfocus={() => onHover(d.id)}
					onblur={() => onHover(null)}
					onclick={() => onPin(d.id)}
					onkeydown={(e) => onKey(e, d.id)}
				>
					<title>{d.name}</title>
					<!-- Invisible wide stroke gives the thin curve a usable hit area. -->
					<path d={path} fill="none" stroke="transparent" stroke-width="12" />
					<path d={path} fill="none" stroke={colorScale(d.success_rate)} stroke-width={isActive(d.id) ? 1.6 : 0.8} stroke-opacity="0.7" />
					{#each pts as p, i (i)}
						<circle cx={p[0]} cy={p[1]} r={isActive(d.id) ? 2.4 : 1.6} fill={colorScale(d.success_rate)} opacity="0.85" />
					{/each}
					{#if isActive(d.id) && pts.length}
						{@const last = pts[pts.length - 1]}
						<text x={last[0] + 6} y={last[1] + 3} fill="var(--text)" font-size="10.5" font-family="var(--mono)" style="pointer-events:none">{d.name}</text>
					{/if}
				</g>
			{/each}
		</g>
	{:else}
	<g>
		{#each points as d (d.id)}
			<g style="opacity:{isDim(d.id) ? 0.18 : 1};transition:opacity 120ms ease">
				<circle
					cx={xScale(val(d, xKey))}
					cy={yScale(val(d, yKey))}
					r={r(d)}
					fill="var(--accent)"
					fill-opacity={isActive(d.id) ? 0.95 : 0.72}
					stroke={isActive(d.id) ? 'var(--text)' : 'var(--point-stroke)'}
					stroke-width={isActive(d.id) ? 1.5 : 1}
					style="cursor:pointer;transition:fill-opacity 120ms,stroke 120ms"
					role="button"
					tabindex="0"
					aria-label={d.name}
					onmouseenter={() => onHover(d.id)}
					onmouseleave={() => onHover(null)}
					onfocus={() => onHover(d.id)}
					onblur={() => onHover(null)}
					onclick={() => onPin(d.id)}
					onkeydown={(e) => onKey(e, d.id)}
				>
					<title>{d.name}</title>
				</circle>
				{#if isActive(d.id)}
					<text
						x={xScale(val(d, xKey)) + r(d) + 6}
						y={yScale(val(d, yKey)) + 3}
						fill="var(--text)"
						font-size="10.5"
						font-family="var(--mono)"
						style="pointer-events:none">{d.name}</text
					>
				{/if}
			</g>
		{/each}
	</g>
	{/if}
	</svg>
{/if}
