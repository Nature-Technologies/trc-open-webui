import { marked } from 'marked';
import { describe, expect, it } from 'vitest';
import {
	cleanTrcFollowUp,
	extractTrcFollowUps,
	isTrcFollowUpsToken,
	trcFollowUpsFromParts
} from './trc-followups';

const block = (body: string) => '```trc:followups\n' + body + '\n```';
const answer = (body: string) => 'By AUM, as of 2026-10-13 (Addepar).\n\n' + block(body);

describe('extractTrcFollowUps', () => {
	it('reads one or two items from the outlet block', () => {
		expect(extractTrcFollowUps(answer('["Same list by relationship strength"]'))).toEqual([
			'Same list by relationship strength'
		]);
		expect(
			extractTrcFollowUps(
				answer('["Same list by relationship strength","Break down the top client by account"]')
			)
		).toEqual(['Same list by relationship strength', 'Break down the top client by account']);
	});

	it('returns [] with no block', () => {
		expect(extractTrcFollowUps('Plain answer with no follow-ups.')).toEqual([]);
		expect(extractTrcFollowUps('')).toEqual([]);
	});

	it.each([
		['invalid JSON', '["Unclosed"'],
		['an object', '{"a":"b"}'],
		['a bare string', '"Just text"'],
		['an empty array', '[]']
	])('returns [] for %s', (_, body) => {
		expect(extractTrcFollowUps(answer(body))).toEqual([]);
	});

	it('keeps at most two items', () => {
		expect(extractTrcFollowUps(answer('["First","Second","Third"]'))).toEqual(['First', 'Second']);
	});

	it('drops an item over 120 characters and keeps the rest', () => {
		const long = 'x'.repeat(121);
		const edge = 'y'.repeat(120);
		expect(extractTrcFollowUps(answer(JSON.stringify([long, 'Short one', edge])))).toEqual([
			'Short one',
			edge
		]);
	});

	it('counts characters, not UTF-16 units, so 120 emoji still fit', () => {
		const emoji = '\u{1F4C8}'.repeat(120);
		expect(extractTrcFollowUps(answer(JSON.stringify([emoji])))).toEqual([emoji]);
	});

	it.each([
		['an https URL', '"Open https://example.invalid/report"'],
		['a URL with another scheme', '"See ftp://example.invalid"'],
		['an HTML tag', '"Show <img src=x onerror=alert(1)>"'],
		['a closing angle bracket', '"Revenue > budget"'],
		['a JSON-escaped tag', '"Show \\u003cb\\u003ebold\\u003c/b\\u003e"'],
		['a placeholder token', '"Profile of <PERSON_3>"'],
		['an unresolved token', '"Profile of [unavailable]"']
	])('drops an item containing %s', (_, item) => {
		expect(extractTrcFollowUps(answer('[' + item + ',"Safe item"]'))).toEqual(['Safe item']);
	});

	it.each([
		['a number', '[42,"Safe item"]'],
		['null', '[null,"Safe item"]'],
		['a nested list', '[["a"],"Safe item"]'],
		['an object', '[{"text":"a"},"Safe item"]'],
		['an empty string', '["","Safe item"]'],
		['whitespace only', '["   ","Safe item"]']
	])('drops a non-text item: %s', (_, body) => {
		expect(extractTrcFollowUps(answer(body))).toEqual(['Safe item']);
	});

	it('flattens line breaks and tabs to single spaces', () => {
		expect(extractTrcFollowUps(answer('["Top 10\\nclients\\tby AUM"]'))).toEqual([
			'Top 10 clients by AUM'
		]);
	});

	it('drops a duplicate item', () => {
		expect(extractTrcFollowUps(answer('["Same","Same","Other"]'))).toEqual(['Same', 'Other']);
	});

	it('uses the last block when there are several, even if the last is invalid', () => {
		const two = answer('["Earlier"]') + '\n\n' + block('["Later"]');
		expect(extractTrcFollowUps(two)).toEqual(['Later']);
		const lastBroken = answer('["Earlier"]') + '\n\n' + block('not json');
		expect(extractTrcFollowUps(lastBroken)).toEqual([]);
	});

	it('finds a block mid-message, and one followed by the citation block', () => {
		const mid = 'Lead line.\n\n' + block('["Mid item"]') + '\n\nA closing sentence.';
		expect(extractTrcFollowUps(mid)).toEqual(['Mid item']);
		const cited = answer('["Cited item"]') + '\n\n<!--trc:cite {"S1":{"name":"memo.pdf"}}-->';
		expect(extractTrcFollowUps(cited)).toEqual(['Cited item']);
	});

	it.each([
		['four backticks', '````trc:followups\n["A"]\n````'],
		['tildes', '~~~trc:followups\n["A"]\n~~~'],
		['an extra info word', '```trc:followups extra\n["A"]\n```'],
		['no closing fence', '```trc:followups\n["A"]'],
		['a quoted block', '> ```trc:followups\n> ["A"]\n> ```'],
		['an indented block', '    ```trc:followups\n    ["A"]\n    ```']
	])('ignores a non-exact fence: %s', (_, md) => {
		expect(extractTrcFollowUps('Answer.\n\n' + md)).toEqual([]);
	});

	it('never throws on hostile input', () => {
		const deep = '```trc:followups\n' + '['.repeat(5000) + '\n```';
		const nul = '\u0000```trc:followups\n[]\n```';
		expect(() => extractTrcFollowUps(deep)).not.toThrow();
		expect(() => extractTrcFollowUps(nul)).not.toThrow();
	});
});

describe('isTrcFollowUpsToken (what MarkdownTokens hides)', () => {
	const firstCode = (md: string) =>
		marked.lexer(md).find((t: { type: string }) => t.type === 'code');

	it.each([
		['the exact fence', block('["A"]')],
		['invalid JSON inside', block('{oops')],
		['four backticks', '````trc:followups\n["A"]\n````'],
		['tildes', '~~~trc:followups\n["A"]\n~~~'],
		['an extra info word', '```trc:followups extra\n["A"]\n```'],
		['upper case', '```TRC:FOLLOWUPS\n["A"]\n```'],
		['an unclosed fence while streaming', '```trc:followups\n["A"']
	])('hides %s', (_, md) => {
		expect(isTrcFollowUpsToken(firstCode(md))).toBe(true);
	});

	it.each([
		['a python block', '```python\nprint(1)\n```'],
		['a trc-doc card', '```trc-doc\n{"v":1}\n```'],
		['a plain fence', '```\n["A"]\n```']
	])('leaves %s alone', (_, md) => {
		expect(isTrcFollowUpsToken(firstCode(md))).toBe(false);
	});

	it('is false for non-code tokens and for nothing', () => {
		expect(isTrcFollowUpsToken({ type: 'paragraph', lang: 'trc:followups' })).toBe(false);
		expect(isTrcFollowUpsToken(null)).toBe(false);
		expect(isTrcFollowUpsToken(undefined)).toBe(false);
	});
});

describe('cleanTrcFollowUp', () => {
	it('trims and keeps plain text', () => {
		expect(cleanTrcFollowUp('  Top 5 clients by AUM  ')).toBe('Top 5 clients by AUM');
	});
	it('removes bidi overrides and invisible format marks that could spoof the chip', () => {
		expect(cleanTrcFollowUp('Show ‮qes‬ clients⁦')).toBe('Show qes clients');
		expect(cleanTrcFollowUp('Top​ 5﻿ clients')).toBe('Top 5 clients');
	});
	it('keeps a zero-width joiner inside an emoji sequence', () => {
		const family = '\u{1F468}‍\u{1F469}‍\u{1F467}';
		expect(cleanTrcFollowUp(`Plan for ${family}`)).toBe(`Plan for ${family}`);
	});
	it('rejects what is not a string', () => {
		expect(cleanTrcFollowUp(7)).toBeNull();
		expect(cleanTrcFollowUp(undefined)).toBeNull();
	});
});

describe('trcFollowUpsFromParts', () => {
	it('falls back to the output text when content has no block (streamed answers)', () => {
		expect(trcFollowUpsFromParts('', answer('["From output"]'))).toEqual(['From output']);
	});
	it('prefers the content block', () => {
		expect(trcFollowUpsFromParts(answer('["From content"]'), answer('["From output"]'))).toEqual([
			'From content'
		]);
	});
	it('is [] when neither part has a block', () => {
		expect(trcFollowUpsFromParts('plain', 'also plain')).toEqual([]);
	});
});

describe('the tag-on-its-own-line variant a model sometimes writes', () => {
	const variant = (body: string) => '```\ntrc:followups\n' + body + '\n```';

	it('is hidden like any trc:followups fence', () => {
		const [token] = marked.lexer(variant('["A"]'));
		expect(isTrcFollowUpsToken(token as never)).toBe(true);
	});

	it('is parsed into follow-ups', () => {
		expect(
			extractTrcFollowUps('Answer.\n\n' + variant('["Same list by AUM", "Notes on the top two"]'))
		).toEqual(['Same list by AUM', 'Notes on the top two']);
	});

	it('still drops unsafe items and invalid JSON', () => {
		expect(extractTrcFollowUps(variant('["see https://x.example", "Fine"]'))).toEqual(['Fine']);
		expect(extractTrcFollowUps(variant('not json'))).toEqual([]);
	});

	it('leaves an ordinary untagged code block alone', () => {
		const [token] = marked.lexer('```\nprint(1)\n```');
		expect(isTrcFollowUpsToken(token as never)).toBe(false);
	});
});
