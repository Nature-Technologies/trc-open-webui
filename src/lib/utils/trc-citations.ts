// Reads the invisible `<!--trc:cite {…}-->` block the TRC redaction filter appends to an
// assistant message, and strips it from the text that gets rendered. The parsed map is
// keyed by citation marker ("S1", "S2", …) and drives the inline hover cards. Failure is
// never fatal: an absent or unparseable block yields an empty map and (block removed)
// content, never an exception.

export type TrcSource = {
	name: string;
	source?: string;
	as_of?: string;
	url?: string;
	where?: string;
};

const BLOCK = /\n*<!--trc:cite ([\s\S]*?)-->/;

export function extractTrcSources(content: string): {
	content: string;
	sources: Record<string, TrcSource>;
} {
	const m = content.match(BLOCK);
	if (!m) return { content, sources: {} };
	const stripped = content.replace(BLOCK, '');
	try {
		return { content: stripped, sources: JSON.parse(m[1]) };
	} catch {
		return { content: stripped, sources: {} };
	}
}
