import { describe, it, expect } from 'vitest';
import { extractTrcSources } from './trc-citations';

describe('extractTrcSources', () => {
	it('pulls the map and strips the block', () => {
		const raw = 'See [S1].\n\n<!--trc:cite {"S1":{"name":"memo.pdf","source":"dropbox"}}-->';
		const { content, sources } = extractTrcSources(raw);
		expect(content).toBe('See [S1].');
		expect(sources.S1).toEqual({ name: 'memo.pdf', source: 'dropbox' });
	});

	it('returns content unchanged and an empty map when there is no block', () => {
		const { content, sources } = extractTrcSources('plain [S1] answer');
		expect(content).toBe('plain [S1] answer');
		expect(sources).toEqual({});
	});

	it('strips an unparseable block and returns an empty map (never throws)', () => {
		const raw = 'x [S1]\n\n<!--trc:cite {not json-->';
		const { content, sources } = extractTrcSources(raw);
		expect(content).toBe('x [S1]');
		expect(sources).toEqual({});
	});

	it('restores an escaped > in a value', () => {
		const raw = '[S1]\n\n<!--trc:cite {"S1":{"name":"a --\\u003e b"}}-->';
		const { sources } = extractTrcSources(raw);
		expect(sources.S1.name).toBe('a --> b');
	});
});
