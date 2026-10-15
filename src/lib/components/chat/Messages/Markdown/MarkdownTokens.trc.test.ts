import { marked } from 'marked';
import { render } from 'svelte/server';
import { writable } from 'svelte/store';
import { describe, expect, it } from 'vitest';
import MarkdownTokens from './MarkdownTokens.svelte';

// Rendered on the server, so no DOM is needed. HTML comments are Svelte's hydration
// markers, not content, so they are dropped before comparing.
const i18n = writable({ t: (s: string) => s });
const html = (md: string) =>
	render(MarkdownTokens, {
		props: { id: 'm1', tokens: marked.lexer(md), done: true },
		context: new Map([['i18n', i18n]])
	}).body.replace(/<!--[\s\S]*?-->/g, '');

const ANSWER = 'By AUM, as of 2026-10-13 (Addepar).\n\n';

describe('MarkdownTokens hides trc:followups (contract C3)', () => {
	it.each([
		['a valid block', '```trc:followups\n["Same list by relationship strength"]\n```'],
		['invalid JSON', '```trc:followups\n{oops\n```'],
		['four backticks', '````trc:followups\n["A"]\n````'],
		['tildes', '~~~trc:followups\n["A"]\n~~~'],
		['an unclosed fence', '```trc:followups\n["A"]']
	])('renders nothing for %s', (_, fence) => {
		expect(html(ANSWER + fence)).toBe(html(ANSWER));
	});

	it('still renders other code blocks', () => {
		expect(html(ANSWER + '```python\nprint(1)\n```')).not.toBe(html(ANSWER));
	});
});
