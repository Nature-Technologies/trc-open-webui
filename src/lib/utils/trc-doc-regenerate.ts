/**
 * Regenerate for an expired TRC document card (contract C4). Pure: the card feeds every
 * HTTP answer in as an event and renders whatever state comes back, so all the decisions
 * — what to say, whether to poll, when to stop, when to open the viewer — live here.
 */

/** Poll `meta` this often while a report rebuilds in the background (C4: every 3 s). */
export const REGEN_POLL_MS = 3_000;
/** ...and give up after this long (C4: up to 5 minutes). */
export const REGEN_POLL_LIMIT_MS = 5 * 60_000;

export const REGEN_TEXT = {
	working: 'Rebuilding…',
	original: 'Rebuilt from the original data',
	current: 'Rebuilt with current data',
	refused: 'This document can no longer be rebuilt — ask again to make a new one.',
	gone: 'This document is no longer available. Ask again to get a fresh copy.',
	slow: 'Still rebuilding. Try Regenerate again in a minute.',
	failed: "Couldn't rebuild this document right now. Try again in a moment."
} as const;

export type RegenPhase =
	| 'idle' // nothing asked yet (or a remembered rebuild: see `expiresAt`)
	| 'requesting' // POST in flight
	| 'reloading' // 200 received; re-reading meta before opening
	| 'rebuilding' // 202 received; polling meta
	| 'rebuilt' // fresh copy confirmed by meta
	| 'refused' // 409: cannot be rebuilt
	| 'gone' // 404: unknown, not this user, or not this chat
	| 'failed'; // anything else; Regenerate may be pressed again

export interface RegenState {
	phase: RegenPhase;
	/** Status line for the card; null shows the normal expiry text. */
	message: string | null;
	/** The fresh expiry from meta. It outranks the card fence's own `expires_at`. */
	expiresAt: string | null;
	/** Which data the rebuild used, from the 200 answer (a 202 re-runs: current data). */
	rebuilt: 'original_data' | 'current_data' | null;
	/** Epoch ms after which polling stops; set only while rebuilding. */
	pollUntil: number | null;
	/** One-shot: the card should open the viewer now, then send `opened`. */
	open: boolean;
}

export type RegenEvent =
	| { type: 'start' }
	| { type: 'regenerate'; status: number; body: unknown; now: number }
	| { type: 'meta'; status: number; body: unknown; now: number }
	| { type: 'opened' };

export const initialRegenState = (expiresAt: string | null = null): RegenState => ({
	phase: 'idle',
	message: null,
	expiresAt,
	rebuilt: null,
	pollUntil: null,
	open: false
});

/** Whether Regenerate may be pressed (the card shows it only once the copy has expired). */
export const canRegenerate = (s: RegenState): boolean =>
	s.phase === 'idle' || s.phase === 'failed' || s.phase === 'rebuilt';

/** Whether a request or a poll is outstanding (the button shows "Rebuilding…"). */
export const isRegenBusy = (s: RegenState): boolean =>
	s.phase === 'requesting' || s.phase === 'reloading' || s.phase === 'rebuilding';

/**
 * The card's status line while Regenerate has something to say, else null (the card
 * then shows its usual expiry text). "Rebuilt …" is dropped once that copy expires too.
 */
export const regenStatus = (s: RegenState, expired: boolean): string | null =>
	s.phase === 'rebuilt' && expired ? null : s.message;

/**
 * Fresh copies made in this page, by document id, so a re-mounted card stays fresh. Never
 * evicted on purpose: it lives for one page session, holds one short entry per document
 * rebuilt by hand, and a reload empties it.
 */
export const rebuiltTrcDocs = new Map<string, string>();

const obj = (v: unknown): Record<string, unknown> | null =>
	v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : null;

/** A meta body's expiry when it is a real time still in the future, else null. */
const freshExpiry = (body: unknown, now: number): string | null => {
	const at = obj(body)?.expires_at;
	if (typeof at !== 'string') return null;
	const t = new Date(at).getTime();
	return Number.isNaN(t) || t <= now ? null : at;
};

const fail = (s: RegenState, message: string, phase: RegenPhase = 'failed'): RegenState => ({
	...s,
	phase,
	message,
	pollUntil: null,
	open: false
});

const done = (s: RegenState, expiresAt: string): RegenState => ({
	...s,
	phase: 'rebuilt',
	message: s.rebuilt === 'original_data' ? REGEN_TEXT.original : REGEN_TEXT.current,
	expiresAt,
	pollUntil: null,
	open: true
});

export const regenerateState = (s: RegenState, e: RegenEvent): RegenState => {
	switch (e.type) {
		case 'start':
			return canRegenerate(s)
				? { ...s, phase: 'requesting', message: REGEN_TEXT.working, open: false }
				: s;
		case 'opened':
			return { ...s, open: false };
		case 'regenerate': {
			if (s.phase !== 'requesting') return s;
			const b = obj(e.body);
			if (e.status === 200 && b?.status === 'ok') {
				const rebuilt = b.rebuilt === 'original_data' ? 'original_data' : 'current_data';
				return { ...s, phase: 'reloading', rebuilt };
			}
			if (e.status === 202 && b?.status === 'pending') {
				return {
					...s,
					phase: 'rebuilding',
					rebuilt: 'current_data',
					pollUntil: e.now + REGEN_POLL_LIMIT_MS
				};
			}
			if (e.status === 409) return fail(s, REGEN_TEXT.refused, 'refused');
			if (e.status === 404) return fail(s, REGEN_TEXT.gone, 'gone');
			return fail(s, REGEN_TEXT.failed);
		}
		case 'meta': {
			if (s.phase !== 'reloading' && s.phase !== 'rebuilding') return s;
			const fresh = e.status === 200 ? freshExpiry(e.body, e.now) : null;
			if (fresh) return done(s, fresh);
			if (s.phase === 'reloading') return fail(s, REGEN_TEXT.failed);
			// Rebuilding: meta is 404 until the new copy lands; keep polling to the limit.
			return e.now >= (s.pollUntil ?? 0) ? fail(s, REGEN_TEXT.slow) : s;
		}
	}
};
