import { Marked } from 'marked';
import { render } from 'svelte/server';
import { writable } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('dompurify', () => ({ default: { sanitize: (html: string) => html } }));

import trcExt from '$lib/utils/marked/trc-citation-extension';
import MarkdownTokens from './MarkdownTokens.svelte';

// A link in a model answer is a click-only exfiltration channel (the URL carries whatever the
// model put in it), so at render time only a same-origin target becomes an <a>; any other
// target is shown as its text. Rendered on the server, so no DOM is needed.
const i18n = writable({ t: (s: string) => s });
const marked = new Marked();
marked.use(trcExt());
const html = (md: string) =>
	render(MarkdownTokens, {
		props: { id: 'm1', tokens: marked.lexer(md), done: true },
		context: new Map([['i18n', i18n]])
	}).body.replace(/<!--[\s\S]*?-->/g, '');

beforeEach(() => {
	vi.spyOn(console, 'warn').mockImplementation(() => {});
	vi.spyOn(console, 'error').mockImplementation(() => {});
	vi.stubGlobal('window', {
		location: { origin: 'https://app.example' },
		addEventListener: () => {},
		removeEventListener: () => {}
	});
	vi.stubGlobal('document', { body: { style: {} } });
});
afterEach(() => {
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
});

describe('external links in a message render as text only', () => {
	it.each([
		['an https link', '[Open it](https://attacker.invalid/p?q=restored)'],
		['an http link', '[Open it](http://attacker.invalid/p)'],
		['a scheme-less http: link', '[Open it](http:attacker.invalid)'],
		['a protocol-relative link', '[Open it](//attacker.invalid/p)'],
		['a look-alike of the app origin', '[Open it](https://app.example.attacker.invalid/p)'],
		['a userinfo link', '[Open it](https://app.example@attacker.invalid/p)'],
		['a javascript: link', '[Open it](javascript:alert(1))'],
		['a data: link', '[Open it](data:text/html;base64,PHNjcmlwdD4=)'],
		['a vbscript: link', '[Open it](vbscript:msgbox)'],
		['a file: link', '[Open it](file:///etc/hostname)'],
		['a mailto: link', '[Open it](mailto:a@attacker.invalid)'],
		['a reference link', '[Open it][r]\n\n[r]: https://attacker.invalid/p'],
		['a GFM autolink', 'see <https://attacker.invalid/p>'],
		['a bare URL', 'see https://attacker.invalid/p?q=restored now'],
		['a www URL', 'see www.attacker.invalid/p now']
	])('does not link %s', (_, md) => {
		const out = html(md);
		expect(out).not.toContain('<a');
		expect(out).not.toContain('href=');
	});

	it('keeps the link text, formatted', () => {
		const out = html('[Open **it**](https://attacker.invalid/p)');
		expect(out).toContain('Open <strong>it</strong>');
		expect(out).not.toContain('<a');
	});

	it('shows a bare URL as plain text', () => {
		expect(html('see https://attacker.invalid/p now')).toContain('https://attacker.invalid/p');
	});
});

describe('same-origin links and TRC elements still work', () => {
	it.each([
		['a relative path', '[Open](/c/abc)', '/c/abc'],
		['a path with no leading slash', '[Open](files/f1)', 'files/f1'],
		[
			'an absolute same-origin URL',
			'[Open](https://app.example/c/abc)',
			'https://app.example/c/abc'
		],
		['an anchor', '[Open](#section)', '#section']
	])('links %s', (_, md, href) => {
		const out = html(md);
		expect(out).toContain('<a');
		expect(out).toContain(`href="${href}"`);
	});

	it('still renders a [Sn] citation chip', () => {
		const out = html('Revenue grew [S3].');
		expect(out).toContain('S3');
	});

	it('still renders the report download button for a same-origin URL', () => {
		const out = html('[⬇ Download PDF](/api/v1/trc/docs/report/R/pdf)');
		expect(out).toContain('href="/api/v1/trc/docs/report/R/pdf"');
		expect(out).toContain('Download PDF');
		expect(out).toContain('bg-blue-600');
	});

	it('does not render the download button for an external URL', () => {
		const out = html('[⬇ Download PDF](https://attacker.invalid/x.pdf)');
		expect(out).not.toContain('<a');
		expect(out).not.toContain('bg-blue-600');
	});

	it('still renders a trc-doc card', () => {
		const card = JSON.stringify({
			v: 1,
			kind: 'report',
			id: 'R'.repeat(32),
			title: null,
			rows: null,
			pages: 3,
			formats: ['md', 'pdf'],
			expires_at: '2999-01-01T00:15:00+00:00',
			issued_at: '2020-01-01T00:00:00+00:00'
		});
		expect(html('```trc-doc\n' + card + '\n```')).toContain('Open');
	});
});
