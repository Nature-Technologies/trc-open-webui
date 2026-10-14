import { marked } from 'marked';
import { render } from 'svelte/server';
import { writable } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// DOMPurify needs a browser (without one it has no sanitize at all); HTMLToken only needs a
// string back, so an identity stand-in is enough to render its branches on the server.
vi.mock('dompurify', () => ({ default: { sanitize: (html: string) => html } }));

import MarkdownTokens from './MarkdownTokens.svelte';

// A model answer is attacker-influenced text over restored client data, so what it can make
// the browser fetch is limited at render time: an external image is never loaded and the
// video, audio and iframe embeds a message can ask for are never created. Rendered on the
// server, so no DOM is needed; HTML comments are Svelte's markers, not content.
const i18n = writable({ t: (s: string) => s });
const html = (md: string) =>
	render(MarkdownTokens, {
		props: { id: 'm1', tokens: marked.lexer(md), done: true },
		context: new Map([['i18n', i18n]])
	}).body.replace(/<!--[\s\S]*?-->/g, '');

describe('images in a message', () => {
	// What the image component and the origin check read from the browser.
	beforeEach(() => {
		vi.stubGlobal('window', {
			location: { origin: 'https://app.example' },
			addEventListener: () => {},
			removeEventListener: () => {}
		});
		vi.stubGlobal('document', { body: { style: {} } });
	});
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it.each([
		['an https image', 'https://attacker.invalid/p.png?q=restored'],
		['an http image', 'http://attacker.invalid/p.png'],
		['a protocol-relative image', '//attacker.invalid/p.png'],
		['a backslash-host image', '/\\attacker.invalid/p.png'],
		['a look-alike of the app origin', 'http://localhost:8080.attacker.invalid/p.png'],
		['a file: image', 'file:///etc/hostname'],
		['a javascript: image', 'javascript:alert(1)']
	])('does not load %s: it shows the alt text instead', (_, url) => {
		const out = html(`![Quarterly chart](${url})`);
		expect(out).not.toContain('<img');
		expect(out).not.toContain('attacker.invalid');
		expect(out).not.toContain('src=');
		expect(out).toContain('Quarterly chart');
	});

	it('shows a plain label when an external image has no alt text', () => {
		const out = html('![](https://attacker.invalid/p.png)');
		expect(out).not.toContain('<img');
		expect(out).not.toContain('attacker.invalid');
		expect(out).toContain('image');
	});

	it.each([
		['a same-origin path', '/api/v1/files/f1/content', '/api/v1/files/f1/content'],
		[
			'a same-origin absolute URL',
			'https://app.example/api/v1/files/f1/content',
			'https://app.example/api/v1/files/f1/content'
		],
		['a data: image', 'data:image/png;base64,iVBORw0KGgo=', 'data:image/png;base64,iVBORw0KGgo='],
		['a blob: image', 'blob:https://app.example/0a1b2c', 'blob:https://app.example/0a1b2c']
	])('still renders %s', (_, url, src) => {
		const out = html(`![Chart](${url})`);
		expect(out).toContain('<img');
		expect(out).toContain(`src="${src}"`);
	});
});

describe('embeds in a message', () => {
	// An inline <video> or <audio> reaches the renderer as separate tag and text tokens: the
	// tags must produce nothing (not an element, not their own text); the words between them
	// are ordinary text.
	it.each([
		['a video', '<video>https://attacker.invalid/v.mp4</video>'],
		['an audio clip', '<audio>https://attacker.invalid/a.mp3</audio>']
	])('creates no element and shows no tag for %s', (_, md) => {
		const out = html(md);
		expect(out).not.toMatch(/<(video|audio)\b/);
		expect(out).not.toMatch(/&lt;\/?(video|audio)/);
		expect(out).not.toContain('src=');
	});

	it.each([
		[
			'a YouTube iframe',
			'<iframe width="560" src="https://www.youtube.com/embed/dQw4w9WgXcQ"></iframe>'
		],
		['an iframe', '<iframe src="https://attacker.invalid/frame"></iframe>']
	])('renders nothing at all for %s', (_, md) => {
		const out = html(md);
		expect(out).not.toMatch(/<iframe\b/);
		expect(out).not.toContain('attacker.invalid');
		expect(out).not.toContain('youtube');
		expect(out.trim()).toBe('');
	});

	it('still renders the iframe for a file the backend itself attached', () => {
		const out = html('<file type="html" id="f1"></file>');
		expect(out).toContain('<iframe');
		expect(out).toContain('/api/v1/files/f1/content/html');
	});
});
