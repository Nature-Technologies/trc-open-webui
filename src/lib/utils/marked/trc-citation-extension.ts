// Recognises TRC citation markers of the form [S<digits>] (e.g. [S67]) as an inline
// token, so the renderer can turn each into a hover card sourced from the `trc:cite`
// content block. Deliberately distinct from `citation-extension.ts`, which handles the
// numeric [1] / [1,2] form — a marker here always carries the `S` prefix, so the two
// never collide. `start` mirrors the native extension (returns `src.search(...)`, i.e.
// -1 when absent).
export function trcCitationExtension() {
	return {
		name: 'trcCitation',
		level: 'inline' as const,

		start(src: string) {
			return src.search(/\[S\d/);
		},

		tokenizer(src: string) {
			const m = /^\[S(\d+)\]/.exec(src);
			if (!m) return;
			return {
				type: 'trcCitation',
				raw: m[0],
				marker: `S${m[1]}`
			};
		},

		renderer(token: any) {
			// Fallback only — the Svelte renderer (MarkdownInlineTokens) draws the card.
			return token.raw;
		}
	};
}

export default function () {
	return {
		extensions: [trcCitationExtension()]
	};
}
