import { describe, expect, it, vi } from 'vitest';

vi.mock('$lib/constants', () => ({ WEBUI_BASE_URL: 'https://app.example' }));

import { messageImageSrc, messageLinkHref, safeImageUrl } from './safeImageUrl';

const PLACEHOLDER = 'https://app.example/favicon.png';

describe('safeImageUrl', () => {
	it.each([
		['a protocol-relative URL', '//attacker.invalid/p.png'],
		['a backslash-host URL', '/\\attacker.invalid/p.png'],
		['a look-alike of the app origin', 'https://app.example.attacker.invalid/p.png'],
		['an external URL', 'https://attacker.invalid/p.png'],
		['a javascript: URL', 'javascript:alert(1)']
	])('replaces %s with the placeholder', (_, url) => {
		expect(safeImageUrl(url)).toBe(PLACEHOLDER);
	});

	it.each([
		'/api/v1/files/f1/content',
		'https://app.example/api/v1/files/f1/content',
		'data:image/png;base64,iVBORw0KGgo=',
		'blob:https://app.example/0a1b2c'
	])('keeps %s', (url) => {
		expect(safeImageUrl(url)).toBe(url);
	});

	it('replaces a data: URL that is not an image, in any case', () => {
		expect(safeImageUrl('data:text/html;base64,PHNjcmlwdD4=')).toBe(PLACEHOLDER);
		expect(safeImageUrl('DATA:TEXT/HTML,hi')).toBe(PLACEHOLDER);
	});

	it.each(['DATA:IMAGE/PNG;base64,iVBORw0KGgo=', 'BLOB:https://app.example/0a1b2c'])(
		'keeps the odd-case scheme %s, as messageImageSrc lets it through',
		(url) => {
			expect(safeImageUrl(url)).toBe(url);
		}
	);
});

describe('messageImageSrc', () => {
	const origins = ['https://app.example'];

	it.each([
		['a relative path', '/api/v1/files/f1/content'],
		['a path with no leading slash', 'files/f1.png'],
		['an absolute URL on the app origin', 'https://app.example/api/v1/files/f1/content'],
		['a data: image', 'data:image/png;base64,iVBORw0KGgo='],
		['an upper-case DATA: image', 'DATA:IMAGE/PNG;base64,iVBORw0KGgo='],
		['a blob: URL', 'blob:https://app.example/0a1b2c']
	])('lets %s load', (_, url) => {
		expect(messageImageSrc(url, origins)).toBe(url);
	});

	it.each([
		['an external https URL', 'https://attacker.invalid/p.png?q=restored'],
		['an external http URL', 'http://attacker.invalid/p.png'],
		['a protocol-relative URL', '//attacker.invalid/p.png'],
		['a backslash-host URL', '/\\attacker.invalid/p.png'],
		['a tab-split scheme', 'ht\ttps://attacker.invalid/p.png'],
		['a look-alike of the app origin', 'https://app.example.attacker.invalid/p.png'],
		['the app origin with userinfo', 'https://app.example@attacker.invalid/p.png'],
		['another port on the app host', 'https://app.example:8443/p.png'],
		['a data: URL that is not an image', 'data:text/html;base64,PHNjcmlwdD4='],
		['a file: URL', 'file:///etc/hostname'],
		['a javascript: URL', 'javascript:alert(1)'],
		['an empty value', ''],
		['nothing', undefined]
	])('refuses %s', (_, url) => {
		expect(messageImageSrc(url as string, origins)).toBeNull();
	});

	it('trusts nothing but relative URLs when it knows no origin', () => {
		expect(messageImageSrc('/a.png', [])).toBe('/a.png');
		expect(messageImageSrc('https://app.example/a.png', [])).toBeNull();
	});
});

describe('messageLinkHref', () => {
	const origins = ['https://app.example'];

	it.each([
		'/c/abc',
		'files/f1',
		'#top',
		'?q=1',
		'https://app.example/c/abc',
		'HTTPS://APP.EXAMPLE/c/abc'
	])('keeps %s', (url) => {
		expect(messageLinkHref(url, origins)).toBe(url);
	});

	it.each([
		'https://attacker.invalid/p',
		'http:attacker.invalid',
		'https:attacker.invalid',
		'//attacker.invalid/p',
		'/\\attacker.invalid/p',
		'\\\\attacker.invalid/p',
		'https://app.example@attacker.invalid/p',
		'https://app.example.attacker.invalid/p',
		'ht\ttp://attacker.invalid',
		' javascript:alert(1)',
		'JaVaScRiPt:alert(1)',
		'data:text/html,hi',
		'vbscript:x',
		'file:///etc/hostname',
		'mailto:a@attacker.invalid',
		'blob:https://app.example/0a1b2c',
		'',
		null,
		undefined
	])('refuses %j', (url) => {
		expect(messageLinkHref(url as never, origins)).toBeNull();
	});
});
