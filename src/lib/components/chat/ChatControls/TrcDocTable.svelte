<script lang="ts">
	// The Table tab of the TRC document viewer. Cells are plain strings from parseCsv and are
	// rendered as text ({cell}), never as HTML. The filter narrows the rows already rendered
	// (at most 1,000) client-side; it never asks the server for anything.
	export let header: string[] = [];
	export let rows: string[][] = [];
	export let total = 0;
	export let expired = false;

	let query = '';

	const NUMERIC = /^[-+]?[$£€]?\d[\d,]*(\.\d+)?%?$/;
	const isNumericColumn = (i: number) => {
		const name = (header[i] ?? '').trim().toLowerCase();
		if (name === '#' || name === 'score') return true;
		const sample = rows
			.slice(0, 50)
			.map((r) => (r[i] ?? '').trim())
			.filter(Boolean);
		return sample.length > 0 && sample.every((v) => NUMERIC.test(v));
	};
	$: numeric = header.map((_, i) => isNumericColumn(i));

	$: needle = query.trim().toLowerCase();
	$: visible = needle ? rows.filter((r) => r.some((c) => c.toLowerCase().includes(needle))) : rows;
	$: truncated = total > rows.length;
</script>

<div class="flex h-full min-h-0 flex-col">
	<div class="flex shrink-0 items-center gap-3 px-4 py-2.5">
		<label class="relative min-w-0 flex-1">
			<span class="sr-only">Filter rows</span>
			<svg
				xmlns="http://www.w3.org/2000/svg"
				viewBox="0 0 20 20"
				fill="currentColor"
				aria-hidden="true"
				class="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-gray-400"
			>
				<path
					fill-rule="evenodd"
					d="M9 3.5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11ZM2 9a7 7 0 1 1 12.45 4.39l3.08 3.08a.75.75 0 1 1-1.06 1.06l-3.08-3.08A7 7 0 0 1 2 9Z"
					clip-rule="evenodd"
				/>
			</svg>
			<input
				type="search"
				bind:value={query}
				placeholder="Filter rows"
				autocomplete="off"
				spellcheck="false"
				class="w-full rounded-lg border border-gray-200 bg-transparent py-1.5 pl-8 pr-2.5 text-sm text-gray-900 placeholder:text-gray-400 focus:border-blue-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/30 dark:border-gray-800 dark:text-gray-100 dark:placeholder:text-gray-500"
			/>
		</label>
		<span class="shrink-0 text-xs tabular-nums text-gray-500 dark:text-gray-400" aria-live="polite">
			{#if needle}
				{visible.length.toLocaleString()} of {rows.length.toLocaleString()}
			{:else}
				{rows.length.toLocaleString()}
				{rows.length === 1 ? 'row' : 'rows'}
			{/if}
		</span>
	</div>

	<div class="min-h-0 flex-1 overflow-auto border-t border-gray-100 dark:border-gray-850">
		{#if rows.length === 0}
			<p class="px-4 py-10 text-center text-sm text-gray-500 dark:text-gray-400">
				This list has no rows.
			</p>
		{:else}
			<table class="w-full border-separate border-spacing-0 text-left text-sm">
				<thead>
					<tr>
						{#each header as name, i}
							<th
								scope="col"
								class="sticky top-0 z-10 whitespace-nowrap border-b border-gray-200 bg-white px-3 py-2 text-xs font-medium text-gray-500 first:pl-4 last:pr-4 dark:border-gray-800 dark:bg-gray-900 dark:text-gray-400 {numeric[
									i
								]
									? 'text-right'
									: ''}"
							>
								{name}
							</th>
						{/each}
					</tr>
				</thead>
				<tbody>
					{#each visible as row}
						<tr class="hover:bg-gray-50 dark:hover:bg-gray-850">
							{#each header as _, i}
								<td
									class="whitespace-pre-line border-b border-gray-100 px-3 py-2 align-top text-gray-800 first:pl-4 last:pr-4 dark:border-gray-850 dark:text-gray-200 {numeric[
										i
									]
										? 'text-right tabular-nums'
										: ''}">{row[i] ?? ''}</td
								>
							{/each}
						</tr>
					{/each}
				</tbody>
			</table>

			{#if needle && visible.length === 0}
				<div class="px-4 py-10 text-center text-sm text-gray-500 dark:text-gray-400">
					<p>No rows match “{query.trim()}”.</p>
					<button
						type="button"
						class="mt-2 rounded text-xs font-medium text-blue-600 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:text-blue-400"
						on:click={() => (query = '')}
					>
						Clear filter
					</button>
				</div>
			{/if}

			{#if truncated}
				<p class="px-4 py-3 text-xs text-gray-500 dark:text-gray-400">
					Showing the first {rows.length.toLocaleString()} of {total.toLocaleString()} rows.
					{#if !expired}Download the CSV to see all of them.{/if}
				</p>
			{/if}
		{/if}
	</div>
</div>
