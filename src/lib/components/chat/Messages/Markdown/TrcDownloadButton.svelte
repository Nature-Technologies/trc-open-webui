<script lang="ts">
	// A modern download button that replaces the plain `[⬇ Download PDF](url)` markdown
	// link the TRC backend emits for a generated report. Recognised by MarkdownInlineTokens
	// from the leading ⬇ in the link label; falls back to a normal link on any client that
	// does not render this component. Picks up the brand crimson via the `blue-*` tokens.
	export let href: string;
	export let label: string = 'Download PDF';

	// Drop the backend's leading ⬇ (the component supplies its own icon).
	$: text = label.replace(/^\s*⬇️?\s*/, '').trim() || 'Download PDF';
</script>

<a
	{href}
	target="_blank"
	rel="noopener"
	class="not-prose my-1 inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3.5 py-2 text-sm font-medium text-white no-underline shadow-sm transition-colors hover:bg-blue-700 hover:shadow active:bg-blue-800"
>
	<svg
		xmlns="http://www.w3.org/2000/svg"
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		class="size-4 shrink-0"
	>
		<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
		<path d="M7 10l5 5 5-5" />
		<path d="M12 15V3" />
	</svg>
	{text}
</a>
