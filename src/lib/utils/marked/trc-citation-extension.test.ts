import { describe, it, expect } from 'vitest';
import { Marked } from 'marked';
import trcExt from './trc-citation-extension';
import citationExt from './citation-extension';

function inlineTokens(src: string): any[] {
	const m = new Marked();
	m.use(citationExt());
	m.use(trcExt());
	const blocks = m.lexer(src) as any[];
	const para = blocks.find((b) => b.type === 'paragraph');
	return para?.tokens ?? [];
}

describe('trc-citation-extension', () => {
	it('tokenizes [S67] as a trcCitation carrying the marker', () => {
		const tokens = inlineTokens('[S67]');
		const tok = tokens.find((t) => t.type === 'trcCitation');
		expect(tok).toBeTruthy();
		expect(tok.marker).toBe('S67');
	});

	it('leaves numeric [1] to the native citation extension', () => {
		const tokens = inlineTokens('[1]');
		expect(tokens.some((t) => t.type === 'citation')).toBe(true);
		expect(tokens.some((t) => t.type === 'trcCitation')).toBe(false);
	});

	it('does not match a non-marker like [Sx]', () => {
		const tokens = inlineTokens('[Sx]');
		expect(tokens.some((t) => t.type === 'trcCitation')).toBe(false);
	});
});
