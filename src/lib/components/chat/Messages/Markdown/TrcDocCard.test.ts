import { render } from 'svelte/server';
import { afterEach, describe, expect, it } from 'vitest';
import { rebuiltTrcDocs } from '$lib/utils/trc-doc-regenerate';
import TrcDocCard from './TrcDocCard.svelte';

// Rendered on the server, so no DOM is needed; the click flow is regenerateState's, tested
// in trc-doc-regenerate.test.ts. This pins what the card offers in each state.
const REPORT = 'R'.repeat(32);
const PAST = '2020-01-01T00:15:00+00:00';
const FUTURE = '2999-01-01T00:15:00+00:00';
const fence = (expires_at: string) =>
	JSON.stringify({
		v: 1,
		kind: 'report',
		id: REPORT,
		title: null,
		rows: null,
		pages: 3,
		formats: ['md', 'pdf'],
		expires_at,
		issued_at: '2020-01-01T00:00:00+00:00'
	});
const html = (text: string) =>
	render(TrcDocCard, { props: { text, done: true } }).body.replace(/<!--[\s\S]*?-->/g, '');
const buttons = (out: string) =>
	[...out.matchAll(/<button[^>]*>([\s\S]*?)<\/button>/g)].map((m) =>
		m[1].replace(/<[^>]+>/g, '').trim()
	);

afterEach(() => rebuiltTrcDocs.clear());

describe('TrcDocCard Regenerate (contract C4)', () => {
	it('offers Regenerate, not a dead Expired button, once the copy has expired', () => {
		const out = html(fence(PAST));
		expect(buttons(out)).toEqual(['Regenerate']);
		expect(out).toContain('This copy has expired.');
	});

	it('offers Open while the copy is fresh', () => {
		expect(buttons(html(fence(FUTURE)))).toEqual(['Open']);
	});

	it('stays fresh after a rebuild in this page, though the fence still says expired', () => {
		rebuiltTrcDocs.set(REPORT, FUTURE);
		expect(buttons(html(fence(PAST)))).toEqual(['Open']);
	});
});
