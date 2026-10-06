import { marked } from 'marked';
import { describe, expect, it } from 'vitest';
import { expiryLabel, isExactTrcDocFence, parseCsv, parseTrcDocCard, trcDocUrl } from './trc-doc';

/** The first `code` token marked lexes from `md` (descending into blockquotes). */
const codeToken = (md: string): { raw: string; text: string } => {
	const find = (tokens: any[]): any =>
		tokens.reduce(
			(hit, t) => hit ?? (t.type === 'code' ? t : t.tokens ? find(t.tokens) : null),
			null
		);
	const t = find(marked.lexer(md));
	if (!t) throw new Error('no code token');
	return t;
};
const exact = (md: string) => {
	const t = codeToken(md);
	return isExactTrcDocFence(t.raw, t.text);
};

describe('isExactTrcDocFence', () => {
	const J = '{"v":1,"kind":"list"}';
	it('accepts the backend fence form', () => {
		expect(exact('```trc-doc\n' + J + '\n```')).toBe(true);
		expect(exact('Before.\n\n```trc-doc\n' + J + '\n```\n\nAfter.')).toBe(true);
		expect(isExactTrcDocFence('```trc-doc\n' + J + '\n```\n', J)).toBe(true);
	});
	it('accepts CRLF, because marked normalises it (the backend neutralises it first)', () => {
		expect(exact('```trc-doc\r\n' + J + '\r\n```')).toBe(true);
	});
	it.each([
		['four backticks', '````trc-doc\n' + J + '\n````'],
		['tildes', '~~~trc-doc\n' + J + '\n~~~'],
		['an indented closer', '```trc-doc\n' + J + '\n   ```'],
		['an unclosed fence', '```trc-doc\n' + J],
		['an extra info string', '```trc-doc extra\n' + J + '\n```'],
		['an indented opener', '  ```trc-doc\n  ' + J + '\n  ```']
	])('rejects %s', (_name, md) => {
		expect(exact(md)).toBe(false);
	});
	it('rejects a raw without its closing fence', () => {
		expect(isExactTrcDocFence('```trc-doc\n' + J, J)).toBe(false);
		expect(isExactTrcDocFence('```trc-doc\n' + J + '\n```\n\n', J)).toBe(false);
	});
});

const LIST = 'lst_' + 'A'.repeat(22);
const card = (o: Record<string, unknown> = {}) =>
	JSON.stringify({
		v: 1,
		kind: 'list',
		id: LIST,
		title: 'TRC list — affinity · COMPANY',
		rows: 8631,
		pages: null,
		formats: ['csv', 'pdf'],
		expires_at: '2026-10-06T14:15:00+00:00',
		...o
	});

describe('parseTrcDocCard', () => {
	it('accepts a valid list card', () => {
		expect(parseTrcDocCard(card())?.rows).toBe(8631);
	});
	it('accepts a report card with no title', () => {
		const r = parseTrcDocCard(
			card({
				kind: 'report',
				id: 'R'.repeat(32),
				title: null,
				rows: null,
				pages: 3,
				formats: ['md', 'pdf']
			})
		);
		expect(r?.title).toBeNull();
	});
	it.each([
		['truncated', card().slice(0, 20)],
		['wrong version', card({ v: 2 })],
		['bad kind', card({ kind: 'secret' })],
		['bad list id', card({ id: 'lst_short' })],
		['report id as list', card({ id: 'R'.repeat(32) })],
		['unknown format', card({ formats: ['exe'] })],
		['no formats', card({ formats: [] })],
		['not an object', '[1,2]']
	])('rejects %s', (_, text) => {
		expect(parseTrcDocCard(text)).toBeNull();
	});
});

describe('trcDocUrl', () => {
	it('builds a same-origin, encoded route URL', () => {
		const url = trcDocUrl({ kind: 'list', id: LIST }, 'chat 1/x', 'csv', true);
		expect(url).toContain(`/api/v1/trc/docs/list/${LIST}?`);
		expect(url).toContain('chat_id=chat+1%2Fx');
		expect(url).toContain('format=csv');
		expect(url).toContain('download=true');
	});
});

describe('parseCsv', () => {
	it('strips the BOM, honours quotes, commas and newlines in cells', () => {
		const text = '﻿#,Name\r\n1,"A, ""B"" Ltd"\r\n2,"Line\nBreak"\r\n';
		const out = parseCsv(text);
		expect(out.header).toEqual(['#', 'Name']);
		expect(out.rows).toEqual([
			['1', 'A, "B" Ltd'],
			['2', 'Line\nBreak']
		]);
		expect(out.total).toBe(2);
	});
	it('drops the formula guard only before = + - @', () => {
		const out = parseCsv("#,Name\r\n1,'=SUM(1)\r\n2,'Plain\r\n");
		expect(out.rows.map((r) => r[1])).toEqual(['=SUM(1)', "'Plain"]);
	});
	it('caps rendered rows but reports the true total', () => {
		const body = Array.from({ length: 1500 }, (_, i) => `${i + 1},X`).join('\r\n');
		const out = parseCsv('#,Name\r\n' + body, 1000);
		expect(out.rows.length).toBe(1000);
		expect(out.total).toBe(1500);
	});
	it('handles an empty body', () => {
		expect(parseCsv('#,Name\r\n')).toEqual({ header: ['#', 'Name'], rows: [], total: 0 });
	});
});

describe('expiryLabel', () => {
	const now = new Date('2026-10-06T14:00:00Z');
	it('says how long is left', () => {
		expect(expiryLabel('2026-10-06T14:12:00+00:00', now)).toBe('Available for 12 more minutes');
		expect(expiryLabel('2026-10-06T14:00:40+00:00', now)).toBe('Available for less than a minute');
	});
	it('says when it has expired', () => {
		expect(expiryLabel('2026-10-06T13:59:00+00:00', now)).toBe('Expired');
	});
	it('is null without a time', () => {
		expect(expiryLabel(null, now)).toBeNull();
	});
});
