<script lang="ts">
	import { LinkPreview } from 'bits-ui';
	import type { TrcSource } from '$lib/utils/trc-citations';

	export let marker: string;
	export let source: TrcSource | undefined = undefined;

	const LOGOS: Record<string, string> = {
		addepar: '/assets/sources/addepar.svg',
		affinity: '/assets/sources/affinity.svg',
		dropbox: '/assets/sources/dropbox.svg'
	};

	$: logo = (source?.source && LOGOS[source.source]) || '/assets/sources/document.svg';
	$: detail = [source?.source, source?.as_of].filter(Boolean).join(' · ');
	// Logos are rendered through a CSS mask, not <img>: an <img>-loaded SVG ignores
	// `currentColor` and paints black, which is invisible on the dark card. As a mask the
	// glyph takes the element's background colour, so it stays visible in both themes.
	$: maskStyle = `mask: url('${logo}') center / contain no-repeat; -webkit-mask: url('${logo}') center / contain no-repeat;`;
</script>

{#if source}
	<LinkPreview.Root openDelay={80} closeDelay={80}>
		<LinkPreview.Trigger>
			<button
				type="button"
				aria-label={`Source ${marker}: ${source.name}`}
				class="inline-flex items-center gap-1 align-baseline text-[11px] leading-none font-medium px-1.5 py-[3px] rounded-md cursor-pointer transition-colors text-blue-700 bg-blue-50 ring-1 ring-blue-600/20 hover:bg-blue-100 dark:text-blue-300 dark:bg-blue-400/10 dark:ring-blue-400/25 dark:hover:bg-blue-400/20"
				on:click={() => source?.url && window.open(source.url, '_blank', 'noopener')}
			>
				<span class="size-3 shrink-0 bg-current opacity-80" style={maskStyle}></span>
				{marker}
			</button>
		</LinkPreview.Trigger>
		<LinkPreview.Portal>
			<LinkPreview.Content class="z-[9999]" align="start" strategy="fixed" sideOffset={6}>
				<div
					class="max-w-xs rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-850 shadow-xl p-3 text-xs text-gray-800 dark:text-gray-100"
				>
					<div class="flex items-center gap-2">
						<span
							class="flex size-6 shrink-0 items-center justify-center rounded-md bg-gray-100 dark:bg-gray-800"
						>
							<span class="size-4 bg-gray-600 dark:bg-gray-200" style={maskStyle}></span>
						</span>
						<span class="font-semibold leading-snug line-clamp-2">{source.name}</span>
					</div>
					{#if detail}
						<div class="mt-1.5 capitalize text-gray-500 dark:text-gray-400">{detail}</div>
					{/if}
					{#if source.where}
						<div class="text-gray-500 dark:text-gray-400">{source.where}</div>
					{/if}
					{#if source.url}
						<a
							href={source.url}
							target="_blank"
							rel="noopener"
							class="mt-2 inline-flex items-center gap-1 font-medium text-blue-600 hover:underline dark:text-blue-400"
						>
							Open source ↗
						</a>
					{/if}
				</div>
			</LinkPreview.Content>
		</LinkPreview.Portal>
	</LinkPreview.Root>
{:else}
	<span>[{marker}]</span>
{/if}
