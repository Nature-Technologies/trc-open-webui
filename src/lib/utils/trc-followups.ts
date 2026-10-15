// Reads the ```trc:followups block the TRC redaction filter leaves on a finished answer
// (contract C3) and turns it into the follow-up list Open WebUI's FollowUps.svelte shows.
// Pure and total: a missing, malformed or hostile block yields [] and never throws.
// Every trc:followups fence, valid or not, is hidden from the rendered markdown
// (isTrcFollowUpsToken, used by MarkdownTokens.svelte).
import { marked } from 'marked';

export const TRC_FOLLOWUPS_LANG = 'trc:followups';
export const MAX_TRC_FOLLOWUPS = 2;
export const MAX_TRC_FOLLOWUP_CHARS = 120;

// Same rule as the filter outlet's `_followup_unsafe` (trc-backend integrations/openwebui/
// filter.py), which mirrors the backend's outbound origin rule: a URL in any form (`://`,
// `//host`, `\\host`, a scheme with no slashes such as `http:host`), markdown link/image
// syntax, a backtick, `[[`, or anything that could be markup is dropped. A chip is plain
// text, but it must not read as a link either. Keep the two in step.
const UNSAFE =
	/[/\\]{2}|(?<![A-Za-z0-9+.\-])(?:https?|ftp|wss?|file|javascript|vbscript|data):(?=\S)|\]\(|!\[|`|\[\[|[<>]/i;
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

/**
 * The tag-on-its-own-line form in the one shape the outlet's `_FOLLOWUPS_BLOCK_RE` cuts and
 * re-emits: exactly three backticks, the tag lower-case on a line of its own. Tilde and
 * longer fences, upper-case tags and the like are hidden (above) but never parsed: the
 * outlet neither vets nor removes them, so chips must not be built from them.
 */
const isVettedTagLine = (raw: string): boolean =>
	/^```[ \t]*\r?\n[ \t]*trc:followups[ \t]*(?:\r?\n|$)/.test(raw);

/** The outlet's exact form: "```trc:followups\n" + body + "\n```" (one trailing newline ok). */
const isExactFence = (raw: string, text: string): boolean =>
	(raw.endsWith('\n') ? raw.slice(0, -1) : raw) ===
	'```' + TRC_FOLLOWUPS_LANG + '\n' + text + '\n```';

/**
 * Invisible format characters that can reorder or hide what a chip or title says: soft
 * hyphen, Arabic letter mark, Mongolian vowel separator, zero-width space, bidi marks,
 * overrides and isolates, word joiner and invisible operators, the deprecated format marks
 * U+206A-206F, BOM, and the tag characters. Zero-width joiner/non-joiner stay: emoji
 * sequences and some scripts need them.
 */
const SPOOFING_FORMAT = /[­؜᠎​‎‏‪-‮⁠-⁯﻿\u{E0000}-\u{E007F}]/gu;

/** `text` without the invisible format characters above. */
export const stripSpoofingFormat = (text: string): string => text.replace(SPOOFING_FORMAT, '');

/** One item as plain, single-line text, or null when it must be dropped. */
export const cleanTrcFollowUp = (item: unknown): string | null => {
	if (typeof item !== 'string') return null;
	const text = stripSpoofingFormat(item)
		.replace(/[\s\p{Cc}]+/gu, ' ')
		.trim();
	if (!text || [...text].length > MAX_TRC_FOLLOWUP_CHARS) return null;
	if (UNSAFE.test(text) || text.includes(UNRESOLVED)) return null;
	return text;
};

/**
 * Follow-ups from the LAST top-level trc:followups block in the forms the outlet vets;
 * [] if none is usable.
 */
export const extractTrcFollowUps = (content: string): string[] => {
	if (!content || !content.includes(TRC_FOLLOWUPS_LANG)) return [];
	let last: CodeLike | null = null;
	for (const token of marked.lexer(content)) {
		const t = token as CodeLike;
		if (
			isTrcFollowUpsToken(t) &&
			(isExactFence(t.raw ?? '', t.text ?? '') || isVettedTagLine(t.raw ?? ''))
		)
			last = t;
	}
	if (!last) return [];
	let body: string;
	if (isExactFence(last.raw ?? '', last.text ?? '')) body = last.text ?? '';
	else if (isVettedTagLine(last.raw ?? ''))
		body = (last.text ?? '').split('\n').slice(1).join('\n');
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
