import { describe, it, expect } from 'vitest';
import { extractTrcSources, trcSourcesFromParts } from './trc-citations';

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

describe('trcSourcesFromParts', () => {
	it('falls back to the output text when content has no block (streamed answers)', () => {
		// Streamed answers leave `content` empty; the block rides in the output text.
		const content = '';
		const outputText = 'Total [S1].\n\n<!--trc:cite {"S1":{"name":"memo.pdf"}}-->';
		expect(trcSourcesFromParts(content, outputText).S1).toEqual({ name: 'memo.pdf' });
	});

	it('prefers the content block and ignores the output when content has one', () => {
		const content = '[S1]\n\n<!--trc:cite {"S1":{"name":"from-content.pdf"}}-->';
		const outputText = '[S1]\n\n<!--trc:cite {"S1":{"name":"from-output.pdf"}}-->';
		expect(trcSourcesFromParts(content, outputText).S1.name).toBe('from-content.pdf');
	});

	it('returns an empty map when neither part has a block', () => {
		expect(trcSourcesFromParts('plain', 'also plain')).toEqual({});
	});
});

describe('block never renders as visible text (the staging regression)', () => {
	it('strips a realistic multi-source block off a streamed answer, leaving only prose', () => {
		const answer = 'Here is the fuller record for the person. Want me to open any of them?';
		const raw =
			answer +
			'\n\n<!--trc:cite {"S1":{"name":"Steven Baker","source":"affinity",' +
			'"url":"https://thornapplecapital.affinity.co/persons/129422925"},' +
			'"S30":{"name":"Steven Baker","source":"affinity",' +
			'"url":"https://thornapplecapital.affinity.co/persons/129496496"}}-->';
		const { content, sources } = extractTrcSources(raw);
		expect(content).toBe(answer); // no `<!--trc:cite` residue on screen
		expect(content).not.toContain('trc:cite');
		expect(content).not.toContain('thornapplecapital');
		expect(Object.keys(sources)).toEqual(['S1', 'S30']); // still available for the cards
	});
});
