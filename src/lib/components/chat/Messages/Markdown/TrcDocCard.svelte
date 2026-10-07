<script lang="ts">
	// The chat card for a ```trc-doc fence (trc-backend spec 2026-10-06-document-viewer).
	// Open is disabled until the chat has an id (a saved chat): the viewer route looks the
	// chat up by id, and the backend emits no cards in temporary chats.
	// The fence holds ids and counts only, never a name or a URL; the content is fetched by
	// the viewer panel when the user presses Open. The card is deliberately quiet: it belongs
	// to the message, and its one distinctive element is a content-free glyph of the
	// document's shape (a ruled table for a list, a page for a report).
	import { onDestroy, onMount } from 'svelte';
	import {
		chatId,
		mobile,
		settings,
		showArtifacts,
		showControls,
		showEmbeds,
		showTrcDoc,
		trcDoc
	} from '$lib/stores';
	import {
		autoOpenedTrcDocs,
		expiryLabel,
		parseTrcDocCard,
		shouldAutoOpenTrcDoc
	} from '$lib/utils/trc-doc';

	export let text: string;
	export let done: boolean;

	$: card = parseTrcDocCard(text);

	let now = new Date();
	let timer: ReturnType<typeof setInterval> | undefined;
	onMount(() => {
		timer = setInterval(() => (now = new Date()), 30_000);
	});
	onDestroy(() => {
		if (timer) clearInterval(timer);
	});

	const plural = (n: number, one: string) => `${n.toLocaleString()} ${one}${n === 1 ? '' : 's'}`;

	$: heading = card ? (card.kind === 'list' ? (card.title ?? 'List') : 'Report') : '';
	$: count = !card
		? null
		: card.kind === 'list'
			? card.rows === null
				? null
				: plural(card.rows, 'row')
			: card.pages === null
				? null
				: plural(card.pages, 'page');
	$: expiry = card ? expiryLabel(card.expires_at, now) : null;
	$: expired = expiry === 'Expired';
	$: openLabel = `Open ${card?.kind === 'list' ? (card.title ?? 'list') : 'report'} in the viewer`;

	const open = () => {
		if (!card || !$chatId) return;
		trcDoc.set({ ...card, chatId: $chatId });
		showArtifacts.set(false);
		showEmbeds.set(false);
		showControls.set(true);
		showTrcDoc.set(true);
	};

	// Open by itself once, the moment a just-issued card first appears — the way Open
	// WebUI auto-opens an Artifacts block. Decided ONCE per card: a card that arrived
	// while another panel was open must not pop up later when that panel closes.
	let considered = false;
	$: if (card && !considered) {
		considered = true;
		const autoOpen = shouldAutoOpenTrcDoc(card, {
			enabled: $settings?.autoOpenTrcDocs ?? true,
			mobile: $mobile,
			chatId: $chatId,
			panelBusy: $showArtifacts || $showEmbeds || $showTrcDoc
		});
		// Remembered page-wide whatever the outcome, so a re-render (which re-mounts this
		// card) never reconsiders it — e.g. after the user closed the panel it opened.
		autoOpenedTrcDocs.add(card.id);
		if (autoOpen) open();
	}
</script>

{#if card}
	<div
		role="group"
		aria-label={heading}
		class="not-prose my-2 flex max-w-md items-center gap-3 whitespace-normal rounded-xl border border-gray-200 bg-white px-3 py-2.5 dark:border-gray-800 dark:bg-gray-900"
	>
		<svg
			xmlns="http://www.w3.org/2000/svg"
			viewBox="0 0 40 40"
			aria-hidden="true"
			focusable="false"
			class="size-10 shrink-0 text-gray-500 dark:text-gray-400"
		>
			{#if card.kind === 'list'}
				<!-- A ruled table: a frame, a crimson top rule, two rows of two cells. -->
				<rect
					x="4.5"
					y="5.5"
					width="31"
					height="29"
					rx="3"
					fill="currentColor"
					fill-opacity="0.06"
					stroke="currentColor"
					stroke-opacity="0.35"
				/>
				<path
					d="M4 8.5a3.5 3.5 0 0 1 3.5-3.5h25a3.5 3.5 0 0 1 3.5 3.5V10H4z"
					class="text-blue-600 dark:text-blue-500"
					fill="currentColor"
				/>
				<g fill="currentColor" fill-opacity="0.4">
					<rect x="9" y="15" width="6" height="3" rx="1.5" />
					<rect x="18" y="15" width="13" height="3" rx="1.5" />
					<rect x="9" y="25" width="6" height="3" rx="1.5" />
					<rect x="18" y="25" width="10" height="3" rx="1.5" />
				</g>
				<path d="M5 21.5h30" stroke="currentColor" stroke-opacity="0.2" />
			{:else}
				<!-- A page: an outline, a crimson top rule, three lines of text. -->
				<rect
					x="9.5"
					y="4.5"
					width="21"
					height="31"
					rx="2.5"
					fill="currentColor"
					fill-opacity="0.06"
					stroke="currentColor"
					stroke-opacity="0.35"
				/>
				<path
					d="M9 7a3 3 0 0 1 3-3h16a3 3 0 0 1 3 3v1.5H9z"
					class="text-blue-600 dark:text-blue-500"
					fill="currentColor"
				/>
				<g fill="currentColor" fill-opacity="0.4">
					<rect x="13" y="14" width="14" height="2.5" rx="1.25" />
					<rect x="13" y="19.5" width="14" height="2.5" rx="1.25" />
					<rect x="13" y="25" width="9" height="2.5" rx="1.25" />
				</g>
			{/if}
		</svg>

		<div class="min-w-0 flex-1">
			<div class="truncate text-sm font-medium text-gray-900 dark:text-gray-100" title={heading}>
				{heading}
			</div>
			{#if count || expiry}
				<div class="mt-0.5 flex flex-wrap gap-x-3 text-xs text-gray-500 dark:text-gray-400">
					{#if count}
						<span class="tabular-nums">{count}</span>
					{/if}
					{#if expired}
						<span>Ask again to get a fresh copy.</span>
					{:else if expiry}
						<span>{expiry}</span>
					{/if}
				</div>
			{/if}
		</div>

		{#if expired}
			<button
				type="button"
				disabled
				class="shrink-0 cursor-not-allowed rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-500 dark:border-gray-700 dark:text-gray-400"
			>
				Expired
			</button>
		{:else}
			<button
				type="button"
				aria-label={openLabel}
				disabled={!$chatId}
				on:click={open}
				class="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white shadow-sm transition-colors hover:bg-blue-700 hover:shadow active:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50 disabled:shadow-none disabled:hover:bg-blue-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:focus-visible:ring-offset-gray-900"
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					stroke-linecap="round"
					stroke-linejoin="round"
					aria-hidden="true"
					class="size-3.5 shrink-0"
				>
					<rect x="3" y="4" width="18" height="16" rx="2" />
					<path d="M15 4v16" />
				</svg>
				Open
			</button>
		{/if}
	</div>
{:else if !done}
	<div
		aria-busy="true"
		class="not-prose my-2 flex max-w-md items-center gap-3 whitespace-normal rounded-xl border border-gray-200 bg-white px-3 py-2.5 dark:border-gray-800 dark:bg-gray-900"
	>
		<span class="sr-only">Preparing document</span>
		<div
			aria-hidden="true"
			class="flex min-w-0 flex-1 animate-pulse items-center gap-3 motion-reduce:animate-none"
		>
			<div class="size-10 shrink-0 rounded-lg bg-gray-100 dark:bg-gray-800"></div>
			<div class="min-w-0 flex-1 space-y-2">
				<div class="h-3 w-2/5 rounded bg-gray-100 dark:bg-gray-800"></div>
				<div class="h-2.5 w-3/5 rounded bg-gray-100 dark:bg-gray-800"></div>
			</div>
			<div class="h-7 w-16 shrink-0 rounded-lg bg-gray-100 dark:bg-gray-800"></div>
		</div>
	</div>
{:else}
	{text}
{/if}
