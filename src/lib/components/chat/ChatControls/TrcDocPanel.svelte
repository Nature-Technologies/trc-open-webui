<script lang="ts">
	// The TRC document viewer panel (trc-backend spec 2026-10-06-document-viewer). Content is
	// fetched from the same-origin route and held in this component only: a per-panel Map,
	// cleared when the document changes or the panel closes. Nothing fetched — the title
	// included, which is real PII for a report — goes to a store, storage or the message.
	// The route answers with `Content-Security-Policy: sandbox`, so its URL is never framed:
	// bytes are fetched and rendered here, and only the download links point at it.
	import { onDestroy, onMount, tick } from 'svelte';
	import { showControls, showTrcDoc, trcDoc } from '$lib/stores';
	import { expiryLabel, parseCsv, trcDocUrl, type TrcDocFormat } from '$lib/utils/trc-doc';

	import Markdown from '$lib/components/chat/Messages/Markdown.svelte';
	import PDFViewer from '$lib/components/common/PDFViewer.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import TrcDocTable from './TrcDocTable.svelte';

	type Entry =
		| { state: 'loading' }
		| { state: 'error'; status: number }
		| { state: 'ready'; value: any };
	type Meta = { title?: unknown; rows?: unknown; pages?: unknown; expires_at?: unknown };

	const LABELS: Record<TrcDocFormat, string> = { csv: 'Table', md: 'Document', pdf: 'PDF' };
	const DOWNLOADS: Record<TrcDocFormat, string> = {
		csv: 'Download CSV',
		pdf: 'Download PDF',
		md: 'Download Markdown'
	};
	const ERRORS: Record<number, string> = {
		404: 'This document is no longer available. Ask again to get a fresh copy.',
		502: 'This document is too large to show here. Use the download link instead.'
	};
	const UNAVAILABLE = "The document service can't be reached right now. Try again in a moment.";

	let cache = new Map<TrcDocFormat, Entry>();
	let meta: Meta | null = null;
	let controller: AbortController | null = null;
	let key = '';
	let active: TrcDocFormat = 'csv';
	let headingEl: HTMLElement;
	let tabEls: Record<string, HTMLButtonElement> = {};

	$: doc = $trcDoc;
	$: formats = doc ? doc.formats : [];

	const docKey = (d: typeof doc) => (d ? `${d.chatId}/${d.kind}/${d.id}` : '');
	$: if (docKey(doc) !== key) reset();

	const defaultTab = (d: NonNullable<typeof doc>): TrcDocFormat => {
		const preferred: TrcDocFormat = d.kind === 'list' ? 'csv' : 'md';
		return d.formats.includes(preferred) ? preferred : d.formats[0];
	};

	const read = async (res: Response, fmt: TrcDocFormat | 'meta') =>
		fmt === 'meta'
			? res.json()
			: fmt === 'pdf'
				? res.arrayBuffer()
				: fmt === 'csv'
					? parseCsv(await res.text())
					: res.text();

	const request = async (fmt: TrcDocFormat | 'meta'): Promise<Entry> => {
		const d = doc;
		const signal = controller?.signal;
		if (!d || !signal) return { state: 'error', status: 0 };
		try {
			const res = await fetch(trcDocUrl(d, d.chatId, fmt), { credentials: 'include', signal });
			if (!res.ok) return { state: 'error', status: res.status };
			return { state: 'ready', value: await read(res, fmt) };
		} catch {
			return { state: 'error', status: 0 };
		}
	};

	const load = async (fmt: TrcDocFormat) => {
		const signal = controller?.signal;
		cache.set(fmt, { state: 'loading' });
		cache = cache;
		const entry = await request(fmt);
		if (signal?.aborted) return;
		cache.set(fmt, entry);
		cache = cache;
	};

	const loadMeta = async () => {
		const signal = controller?.signal;
		const entry = await request('meta');
		if (signal?.aborted || entry.state !== 'ready') return;
		meta = entry.value && typeof entry.value === 'object' ? entry.value : null;
	};

	function reset() {
		controller?.abort();
		cache = new Map();
		meta = null;
		key = docKey(doc);
		controller = doc ? new AbortController() : null;
		if (!doc) return;
		active = defaultTab(doc);
		loadMeta();
		load(active);
		tick().then(() => headingEl?.focus({ preventScroll: true }));
	}

	const select = (fmt: TrcDocFormat, focus = false) => {
		active = fmt;
		if (!cache.has(fmt)) load(fmt);
		if (focus) tick().then(() => tabEls[fmt]?.focus());
	};

	const onTabKeydown = (e: KeyboardEvent) => {
		const i = formats.indexOf(active);
		const next =
			e.key === 'ArrowRight'
				? (i + 1) % formats.length
				: e.key === 'ArrowLeft'
					? (i - 1 + formats.length) % formats.length
					: e.key === 'Home'
						? 0
						: e.key === 'End'
							? formats.length - 1
							: -1;
		if (next < 0) return;
		e.preventDefault();
		select(formats[next], true);
	};

	const close = () => {
		controller?.abort();
		showTrcDoc.set(false);
		trcDoc.set(null);
		showControls.set(false);
	};

	const onKeydown = (e: KeyboardEvent) => {
		if (e.key !== 'Escape') return;
		const t = e.target;
		// Never let Escape reach the window: the mobile Drawer closes on it there.
		e.stopPropagation();
		// Escape in a non-empty search box clears it first, as the browser does.
		if (t instanceof HTMLInputElement && t.type === 'search' && t.value) return;
		close();
	};

	let now = new Date();
	let timer: ReturnType<typeof setInterval> | undefined;
	onMount(() => (timer = setInterval(() => (now = new Date()), 30_000)));
	onDestroy(() => {
		if (timer) clearInterval(timer);
		controller?.abort();
		cache.clear();
		meta = null;
	});

	const str = (v: unknown) => (typeof v === 'string' && v.trim() ? v.trim() : null);
	const int = (v: unknown) => (typeof v === 'number' && Number.isInteger(v) && v >= 0 ? v : null);
	const counted = (n: number | null, one: string) =>
		n === null ? null : `${n.toLocaleString()} ${one}${n === 1 ? '' : 's'}`;

	$: title = str(meta?.title) ?? doc?.title ?? (doc?.kind === 'list' ? 'List' : 'Report');
	$: count = !doc
		? null
		: doc.kind === 'list'
			? counted(int(meta?.rows) ?? doc.rows, 'row')
			: counted(int(meta?.pages) ?? doc.pages, 'page');
	$: expiry = doc ? expiryLabel(str(meta?.expires_at) ?? doc.expires_at, now) : null;
	$: expired = expiry === 'Expired';
	$: entry = cache.get(active);
</script>

{#if doc}
	<!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
	<section
		class="flex h-full w-full flex-col bg-white text-gray-900 dark:bg-gray-900 dark:text-gray-100"
		aria-label="Document viewer"
		on:keydown={onKeydown}
	>
		<header
			class="sticky top-0 z-20 flex shrink-0 items-start gap-3 border-b border-gray-100 bg-white px-4 py-3 dark:border-gray-850 dark:bg-gray-900"
		>
			<div class="min-w-0 flex-1">
				<h2
					bind:this={headingEl}
					tabindex="-1"
					class="truncate text-sm font-medium focus:outline-none"
					{title}
				>
					{title}
				</h2>
				{#if count || expiry}
					<div class="mt-0.5 flex flex-wrap gap-x-3 text-xs text-gray-500 dark:text-gray-400">
						{#if count}<span class="tabular-nums">{count}</span>{/if}
						{#if expiry}<span>{expiry}</span>{/if}
					</div>
				{/if}
			</div>
			<button
				type="button"
				aria-label="Close document"
				class="-mr-1 shrink-0 rounded-lg p-1.5 text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-white"
				on:click={close}
			>
				<XMark className="size-4" />
			</button>
		</header>

		<div
			class="flex shrink-0 flex-wrap items-center justify-between gap-x-4 border-b border-gray-100 px-4 dark:border-gray-850"
		>
			<div role="tablist" aria-label="Document format" class="-mb-px flex gap-1">
				{#each formats as fmt}
					<button
						type="button"
						role="tab"
						id="trc-doc-tab-{fmt}"
						aria-selected={active === fmt}
						aria-controls="trc-doc-tabpanel"
						tabindex={active === fmt ? 0 : -1}
						bind:this={tabEls[fmt]}
						on:click={() => select(fmt)}
						on:keydown={onTabKeydown}
						class="border-b-2 px-2.5 py-2.5 text-sm font-medium transition-colors focus-visible:rounded-t focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500 {active ===
						fmt
							? 'border-blue-600 text-gray-900 dark:border-blue-500 dark:text-white'
							: 'border-transparent text-gray-500 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200'}"
					>
						{LABELS[fmt]}
					</button>
				{/each}
			</div>
			<div class="flex flex-wrap items-center gap-x-3 py-2">
				{#if expired}
					<span class="text-xs font-medium text-gray-500 dark:text-gray-400">Expired</span>
				{:else}
					{#each formats as fmt}
						<a
							href={trcDocUrl(doc, doc.chatId, fmt, true)}
							download
							class="rounded text-xs font-medium text-blue-600 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:text-blue-400"
						>
							{DOWNLOADS[fmt]}
						</a>
					{/each}
				{/if}
			</div>
		</div>

		<div
			id="trc-doc-tabpanel"
			role="tabpanel"
			aria-labelledby="trc-doc-tab-{active}"
			aria-busy={!entry || entry.state === 'loading'}
			class="relative min-h-0 flex-1"
		>
			{#if !entry || entry.state === 'loading'}
				<span class="sr-only">Loading</span>
				<div
					aria-hidden="true"
					class="h-full animate-pulse overflow-hidden motion-reduce:animate-none"
				>
					{#if active === 'csv'}
						<div class="px-4 py-2.5">
							<div class="h-8 rounded-lg bg-gray-100 dark:bg-gray-800"></div>
						</div>
						{#each Array(9) as _, i}
							<div class="flex gap-4 border-t border-gray-100 px-4 py-3 dark:border-gray-850">
								<div class="h-3 w-6 rounded bg-gray-100 dark:bg-gray-800"></div>
								<div
									class="h-3 rounded bg-gray-100 dark:bg-gray-800"
									style="width: {35 + ((i * 17) % 30)}%"
								></div>
								<div class="ml-auto h-3 w-10 rounded bg-gray-100 dark:bg-gray-800"></div>
							</div>
						{/each}
					{:else if active === 'md'}
						<div class="mx-auto max-w-3xl space-y-3 px-6 py-6">
							<div class="mb-5 h-5 w-1/2 rounded bg-gray-100 dark:bg-gray-800"></div>
							{#each [92, 100, 84, 96, 60, 0, 88, 100, 72] as w}
								<div class="h-3 rounded bg-gray-100 dark:bg-gray-800" style="width: {w}%"></div>
							{/each}
						</div>
					{:else}
						<div class="flex h-full justify-center bg-gray-50 p-6 dark:bg-gray-850">
							<div
								class="aspect-[1/1.414] h-full max-h-[80vh] rounded bg-gray-100 dark:bg-gray-800"
							></div>
						</div>
					{/if}
				</div>
			{:else if entry.state === 'error'}
				<div
					class="flex h-full flex-col items-center justify-center gap-3 px-8 text-center"
					role="alert"
				>
					<p class="max-w-xs text-sm text-gray-600 dark:text-gray-300">
						{ERRORS[entry.status] ?? UNAVAILABLE}
					</p>
					{#if !ERRORS[entry.status]}
						<button
							type="button"
							class="rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:border-gray-700 dark:text-gray-200 dark:hover:bg-gray-800"
							on:click={() => load(active)}
						>
							Try again
						</button>
					{/if}
				</div>
			{:else if active === 'csv'}
				{#key key}
					<TrcDocTable {...entry.value} {expired} />
				{/key}
			{:else if active === 'md'}
				<div class="h-full overflow-y-auto">
					<div class="mx-auto max-w-3xl px-6 py-6">
						<div class="markdown-prose">
							<Markdown
								id={`trc-doc-${doc.id}`}
								content={entry.value}
								done={true}
								editCodeBlock={false}
							/>
						</div>
					</div>
				</div>
			{:else}
				{#key key}
					<!-- pdf.js transfers (detaches) the buffer it is given, so hand it a copy. -->
					<PDFViewer data={entry.value.slice(0)} className="w-full h-full" />
				{/key}
			{/if}
		</div>
	</section>
{/if}
