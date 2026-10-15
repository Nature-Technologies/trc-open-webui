// Reads the ```trc:followups block the TRC redaction filter leaves on a finished answer
// (contract C3) and turns it into the follow-up list Open WebUI's FollowUps.svelte shows.
// Pure and total: a missing, malformed or hostile block yields [] and never throws.
// Every trc:followups fence, valid or not, is hidden from the rendered markdown
// (isTrcFollowUpsToken, used by MarkdownTokens.svelte).
import { marked } from 'marked';

export const TRC_FOLLOWUPS_LANG = 'trc:followups';
export const MAX_TRC_FOLLOWUPS = 2;
export const MAX_TRC_FOLLOWUP_CHARS = 120;

// Same rule as the filter outlet: a URL or anything that could be markup is dropped.
const UNSAFE = /:\/\/|[<>]/;
// What the outlet writes in place of a token whose mapping is gone.
const UNRESOLVED = '[unavailable]';

type CodeLike = { type?: string; lang?: string; raw?: string; text?: string };

const firstLine = (text: string): string => text.split('\n', 1)[0].trim().toLowerCase();

/**
 * A model sometimes puts the tag on its own line inside an untagged fence:
 * "```\ntrc:followups\n[...]\n```". Treated as the same block.
 */
const isTagLineVariant = (token: CodeLike): boolean =>
	!(token.lang ?? '').trim() && firstLine(token.text ?? '') === TRC_FOLLOWUPS_LANG;

/** Whether a marked token is a trc:followups fence in ANY form — hidden, never rendered. */
export const isTrcFollowUpsToken = (token: CodeLike | null | undefined): boolean =>
	token?.type === 'code' &&
	((token.lang ?? '').trim().split(/\s+/)[0].toLowerCase() === TRC_FOLLOWUPS_LANG ||
		isTagLineVariant(token));

/** The outlet's exact form: "```trc:followups\n" + body + "\n```" (one trailing newline ok). */
const isExactFence = (raw: string, text: string): boolean =>
	(raw.endsWith('\n') ? raw.slice(0, -1) : raw) ===
	'```' + TRC_FOLLOWUPS_LANG + '\n' + text + '\n```';

/** One item as plain, single-line text, or null when it must be dropped. */
export const cleanTrcFollowUp = (item: unknown): string | null => {
	if (typeof item !== 'string') return null;
	const text = item.replace(/[\s\p{Cc}]+/gu, ' ').trim();
	if (!text || [...text].length > MAX_TRC_FOLLOWUP_CHARS) return null;
	if (UNSAFE.test(text) || text.includes(UNRESOLVED)) return null;
	return text;
};

/** Follow-ups from the LAST top-level trc:followups block in `content`; [] if none is usable. */
export const extractTrcFollowUps = (content: string): string[] => {
	if (!content || !content.includes(TRC_FOLLOWUPS_LANG)) return [];
	let last: CodeLike | null = null;
	for (const token of marked.lexer(content)) {
		if (isTrcFollowUpsToken(token as CodeLike)) last = token as CodeLike;
	}
	if (!last) return [];
	let body: string;
	if (isExactFence(last.raw ?? '', last.text ?? '')) body = last.text ?? '';
	else if (isTagLineVariant(last)) body = (last.text ?? '').split('\n').slice(1).join('\n');
	else return [];
	let parsed: unknown;
	try {
		parsed = JSON.parse(body);
	} catch {
		return [];
	}
	if (!Array.isArray(parsed)) return [];
	const out: string[] = [];
	for (const item of parsed) {
		const clean = cleanTrcFollowUp(item);
		if (clean !== null && !out.includes(clean)) out.push(clean);
		if (out.length === MAX_TRC_FOLLOWUPS) break;
	}
	return out;
};

/**
 * Follow-ups for a message, from its flat `content` or, when that has none, from its
 * structured-output text (streamed answers leave `content` empty) — the same fallback
 * trcSourcesFromParts uses for the citation block.
 */
export const trcFollowUpsFromParts = (content: string, outputText: string): string[] => {
	const fromContent = extractTrcFollowUps(content ?? '');
	return fromContent.length > 0 ? fromContent : extractTrcFollowUps(outputText ?? '');
};
