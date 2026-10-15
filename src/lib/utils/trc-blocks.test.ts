import { describe, expect, it } from 'vitest';
import { stripTrcMachineBlocks } from './trc-blocks';

const FOLLOWUPS = '```trc:followups\n["Same list by relationship strength"]\n```';
const DOC = '```trc-doc\n{"v":1,"kind":"list","id":"lst_AAAAAAAAAAAAAAAAAAAAAA"}\n```';
const CITE = '<!--trc:cite {"S1":{"name":"memo.pdf"}}-->';

describe('stripTrcMachineBlocks (the text a user copies)', () => {
	it('leaves a plain answer exactly as it was', () => {
		const text =
			'Top 5 clients by AUM:\n\n| # | Client |\n|---|---|\n| 1 | Synthetic Holdings Ltd |\n';
		expect(stripTrcMachineBlocks(text)).toBe(text);
		expect(stripTrcMachineBlocks('')).toBe('');
	});

	it('drops the follow-ups block and the citation comment the outlet appends', () => {
		const text = `By AUM, as of 2026-10-13.\n\n${FOLLOWUPS}\n\n${CITE}`;
		expect(stripTrcMachineBlocks(text)).toBe('By AUM, as of 2026-10-13.');
	});

	it('drops the document card fence and keeps the text around it', () => {
		const text = `Here is the list.\n\n${DOC}\n\nIt has 12 rows.`;
		const out = stripTrcMachineBlocks(text);
		expect(out).toContain('Here is the list.');
		expect(out).toContain('It has 12 rows.');
		expect(out).not.toContain('trc-doc');
		expect(out).not.toContain('lst_');
	});

	it.each([
		['four backticks', '````trc:followups\n["A"]\n````'],
		['tildes', '~~~trc:followups\n["A"]\n~~~'],
		['invalid JSON', '```trc:followups\n{oops\n```'],
		['upper case', '```TRC:FOLLOWUPS\n["A"]\n```'],
		['an unclosed fence', '```trc:followups\n["A"']
	])('drops a follow-ups fence in any form: %s', (_, fence) => {
		expect(stripTrcMachineBlocks(`Answer.\n\n${fence}`)).toBe('Answer.');
	});

	it('keeps every other code block, including one a user is meant to copy', () => {
		const code = '```python\nprint("hello")\n```';
		const text = `Run this:\n\n${code}\n\n${FOLLOWUPS}\n\n${CITE}`;
		expect(stripTrcMachineBlocks(text)).toBe(`Run this:\n\n${code}`);
	});

	it('drops several machine blocks', () => {
		const text = `One.\n\n${DOC}\n\nTwo.\n\n${FOLLOWUPS}\n\n${CITE}`;
		const out = stripTrcMachineBlocks(text);
		expect(out).toContain('One.');
		expect(out).toContain('Two.');
		expect(out).not.toMatch(/trc[:-]/);
	});
});
