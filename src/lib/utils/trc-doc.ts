/**
 * TRC document viewer helpers (trc-backend spec 2026-10-06-document-viewer).
 *
 * A ```trc-doc fence carries ids and counts only — never a name or a URL. Content is
 * fetched on open from the same-origin `/api/v1/trc/docs` route, which checks the user
 * owns the chat; RAGnarok repeats its own checks. Everything here is pure.
 */
import { WEBUI_BASE_URL } from '$lib/constants';

export type TrcDocKind = 'list' | 'report';
export type TrcDocFormat = 'csv' | 'md' | 'pdf';
export interface TrcDocCardData {
	v: 1;
	kind: TrcDocKind;
	id: string;
	title: string | null;
	rows: number | null;
	pages: number | null;
	formats: TrcDocFormat[];
	expires_at: string | null;
	/** When the backend issued this card — the signal that it just arrived. */
	issued_at: string | null;
}

const ID_SHAPES: Record<TrcDocKind, RegExp> = {
	list: /^lst_[A-Za-z0-9_-]{22}$/,
	report: /^[A-Za-z0-9_-]{32}$/
};
const FORMATS: TrcDocFormat[] = ['csv', 'md', 'pdf'];
const intOrNull = (v: unknown) =>
	typeof v === 'number' && Number.isInteger(v) && v >= 0 ? v : null;

export const parseTrcDocCard = (text: string): TrcDocCardData | null => {
	let raw: unknown;
	try {
		raw = JSON.parse(text);
	} catch {
		return null;
	}
	if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
	const o = raw as Record<string, unknown>;
	if (o.v !== 1 || (o.kind !== 'list' && o.kind !== 'report')) return null;
	const kind = o.kind as TrcDocKind;
	if (typeof o.id !== 'string' || !ID_SHAPES[kind].test(o.id)) return null;
	if (!Array.isArray(o.formats) || o.formats.length === 0) return null;
	if (!o.formats.every((f) => FORMATS.includes(f as TrcDocFormat))) return null;
	return {
		v: 1,
		kind,
		id: o.id,
		title: typeof o.title === 'string' && o.title.trim() ? o.title.trim().slice(0, 120) : null,
		rows: intOrNull(o.rows),
		pages: intOrNull(o.pages),
		formats: [...new Set(o.formats as TrcDocFormat[])],
		expires_at: typeof o.expires_at === 'string' ? o.expires_at : null,
		issued_at: typeof o.issued_at === 'string' ? o.issued_at : null
	};
};

/** How recently a card must have been issued to open itself (ms). */
export const AUTO_OPEN_WINDOW_MS = 60_000;

/** Card ids that have already opened themselves in this page — each opens at most once. */
export const autoOpenedTrcDocs = new Set<string>();

/**
 * Whether a card should open the viewer by itself, the way Open WebUI auto-opens an
 * Artifacts block. Only a card that has JUST arrived (issued within the window — so
 * reopening an old chat or scrolling back never pops anything), only on desktop, only
 * when the user has not turned it off, never twice for one card, and never over a panel
 * the user already has open.
 */
export const shouldAutoOpenTrcDoc = (
	card: TrcDocCardData | null,
	opts: {
		now?: Date;
		enabled: boolean;
		mobile: boolean;
		chatId: string;
		panelBusy: boolean;
		opened?: Set<string>;
	}
): boolean => {
	if (!card || !opts.enabled || opts.mobile || !opts.chatId || opts.panelBusy) return false;
	if ((opts.opened ?? autoOpenedTrcDocs).has(card.id)) return false;
	if (!card.issued_at) return false;
	const issued = new Date(card.issued_at).getTime();
	if (Number.isNaN(issued)) return false;
	const age = (opts.now ?? new Date()).getTime() - issued;
	if (age < -5_000 || age > AUTO_OPEN_WINDOW_MS) return false; // small clock-skew allowance
	return expiryLabel(card.expires_at, opts.now) !== 'Expired';
};

/**
 * Whether a marked `code` token is the backend's exact card fence: "```trc-doc\n" +
 * one JSON line + "\n```" (one trailing newline tolerated). Anything else — ````, ~~~,
 * an indented closer, an unclosed fence, an extra info string — stays a code block, so
 * a model cannot forge a card. marked normalises CRLF (and a bare CR) to "\n" before
 * lexing, so those variants DO pass here; the backend neutralises them before they reach
 * the chat (trc-backend `_defuse_doc_fences`), which is what keeps them out.
 */
export const isExactTrcDocFence = (raw: string, text: string): boolean =>
	(raw.endsWith('\n') ? raw.slice(0, -1) : raw) === '```trc-doc\n' + text + '\n```';

export const trcDocUrl = (
	doc: Pick<TrcDocCardData, 'kind' | 'id'>,
	chatId: string,
	format: TrcDocFormat | 'meta',
	download = false
): string => {
	const q = new URLSearchParams({ chat_id: chatId, format });
	if (download) q.set('download', 'true');
	return `${WEBUI_BASE_URL}/api/v1/trc/docs/${doc.kind}/${encodeURIComponent(doc.id)}?${q.toString()}`;
};

const FORMULA_GUARDED = /^'[=+\-@]/;

/** RFC 4180 parse. Cells are plain strings — render them as text, never as HTML. */
export const parseCsv = (text: string, maxRows = 1000) => {
	const src = text.replace(/^﻿/, '');
	const records: string[][] = [];
	let row: string[] = [];
	let cell = '';
	let quoted = false;
	for (let i = 0; i < src.length; i++) {
		const ch = src[i];
		if (quoted) {
			if (ch === '"') {
				if (src[i + 1] === '"') {
					cell += '"';
					i++;
				} else quoted = false;
			} else cell += ch;
		} else if (ch === '"') quoted = true;
		else if (ch === ',') {
			row.push(cell);
			cell = '';
		} else if (ch === '\n' || ch === '\r') {
			if (ch === '\r' && src[i + 1] === '\n') i++;
			row.push(cell);
			records.push(row);
			row = [];
			cell = '';
		} else cell += ch;
	}
	if (cell !== '' || row.length) {
		row.push(cell);
		records.push(row);
	}
	const unguard = (c: string) => (FORMULA_GUARDED.test(c) ? c.slice(1) : c);
	const [header = [], ...body] = records;
	return {
		header,
		rows: body.slice(0, maxRows).map((r) => r.map(unguard)),
		total: body.length
	};
};

export const expiryLabel = (expiresAt: string | null, now: Date = new Date()): string | null => {
	if (!expiresAt) return null;
	const ms = new Date(expiresAt).getTime() - now.getTime();
	if (Number.isNaN(ms)) return null;
	if (ms <= 0) return 'Expired';
	const minutes = Math.floor(ms / 60000);
	if (minutes < 1) return 'Available for less than a minute';
	return `Available for ${minutes} more minute${minutes === 1 ? '' : 's'}`;
};
