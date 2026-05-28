<script lang="ts">
	import { theme, toggleTheme } from '$lib/theme';

	// Engines are derived upstream from engines.json + leaderboard rows, so adding a
	// backend or swapping hardware needs no change here. `gpu` is "" until that engine
	// has completed runs (we then skip the per-engine hardware stat).
	let { totalModels, engines = [] }: {
		totalModels: number;
		engines?: { label: string; gpu: string }[];
	} = $props();
</script>

<header class="hdr">
	<div class="hdr-l">
		<div class="logo">
			<span class="logo-icon">▲</span>
			<span class="logo-text">llm-grill</span>
			<span class="logo-dot">·</span>
			<span class="logo-sub">benchmark</span>
		</div>
		<nav class="hdr-nav">
			<span class="hdr-link hdr-link-active">scatter</span>
		</nav>
	</div>
	<div class="hdr-r">
		<div class="stat"><span class="stat-n">{totalModels}</span><span class="stat-l">models</span></div>
		<div class="stat"><span class="stat-n">{engines.length}</span><span class="stat-l">backends</span></div>
		{#each engines as e (e.label)}
			{#if e.gpu}
				<div class="stat"><span class="stat-n">{e.gpu}</span><span class="stat-l">{e.label}</span></div>
			{/if}
		{/each}
		<a class="gh-link" title="github" href="https://github.com/llmgrill/llm-grill-platform" aria-label="GitHub">
			<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"
				><path
					d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2 .37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.012 8.012 0 0 0 16 8c0-4.42-3.58-8-8-8z"
				/></svg
			>
		</a>
		<button class="theme-toggle" title="Toggle theme" onclick={toggleTheme} aria-label="Toggle theme">
			{#if $theme === 'dark'}
				<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.3">
					<path d="M11.5 8.2A4.5 4.5 0 0 1 5.8 2.5a5 5 0 1 0 5.7 5.7z" fill="currentColor" />
				</svg>
			{:else}
				<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.3">
					<circle cx="7" cy="7" r="2.5" fill="currentColor" />
					<g stroke-linecap="round">
						<path d="M7 1v1.5M7 11.5V13M1 7h1.5M11.5 7H13M2.6 2.6l1 1M10.4 10.4l1 1M2.6 11.4l1-1M10.4 3.6l1-1" />
					</g>
				</svg>
			{/if}
		</button>
	</div>
</header>
