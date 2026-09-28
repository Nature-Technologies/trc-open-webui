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
</script>

{#if source}
	<LinkPreview.Root openDelay={80} closeDelay={80}>
		<LinkPreview.Trigger>
			<button
				type="button"
				aria-label={`Source ${marker}: ${source.name}`}
				class="text-[10px] w-fit translate-y-[2px] px-1.5 py-0.5 dark:bg-white/5 dark:text-white/80 dark:hover:text-white bg-gray-50 text-black/80 hover:text-black transition rounded-lg align-baseline"
				on:click={() => source?.url && window.open(source.url, '_blank', 'noopener')}
			>
				{marker}
			</button>
		</LinkPreview.Trigger>
		<LinkPreview.Portal>
			<LinkPreview.Content class="z-[9999]" align="start" strategy="fixed" sideOffset={6}>
				<div
					class="max-w-72 rounded-xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-900 shadow-lg p-3 text-xs"
				>
					<div class="flex items-center gap-2">
						<img src={logo} alt="" class="size-4 shrink-0 opacity-80" />
						<span class="font-medium line-clamp-2">{source.name}</span>
					</div>
					{#if detail}
						<div class="mt-1 text-gray-500 dark:text-gray-400">{detail}</div>
					{/if}
					{#if source.where}
						<div class="text-gray-500 dark:text-gray-400">{source.where}</div>
					{/if}
					{#if source.url}
						<a
							href={source.url}
							target="_blank"
							rel="noopener"
							class="mt-2 inline-block text-blue-600 hover:underline"
						>
							Open source
						</a>
					{/if}
				</div>
			</LinkPreview.Content>
		</LinkPreview.Portal>
	</LinkPreview.Root>
{:else}
	<span>[{marker}]</span>
{/if}
