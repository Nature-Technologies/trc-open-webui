// The machine blocks the TRC redaction filter and backend leave in an assistant message:
// the ```trc:followups list, the ```trc-doc card fence and the <!--trc:cite--> comment.
// The UI turns each into something else (follow-up chips, a document card, hover cards), so
// none of them belongs in the text a user copies, reads aloud or inserts into a note.
import { marked } from 'marked';
import { extractTrcSources } from './trc-citations';
import { isTrcFollowUpsToken } from './trc-followups';

type CodeLike = { type?: string; lang?: string; raw?: string };

const isTrcDocToken = (token: CodeLike): boolean =>
	token.type === 'code' && (token.lang ?? '').trim().split(/\s+/)[0].toLowerCase() === 'trc-doc';

/**
 * `text` without its TRC machine blocks; the very same string when it has none.
 * Top-level blocks only: a fence nested in a blockquote or list item is hidden when rendered
 * but stays in the copied text (its raw cannot be cut out of the parent without rewriting
 * the quote/list markers). The outlet only ever writes the fences at top level.
 */
export const stripTrcMachineBlocks = (text: string): string => {
	if (!text || !/trc[:-]/i.test(text)) return text;

	const withoutCite = extractTrcSources(text).content;
	const tokens = marked.lexer(withoutCite) as CodeLike[];
	const kept = tokens.filter((t) => !isTrcFollowUpsToken(t) && !isTrcDocToken(t));
	if (kept.length === tokens.length && withoutCite === text) return text;

	return kept
		.map((t) => t.raw ?? '')
		.join('')
		.trimEnd();
};
