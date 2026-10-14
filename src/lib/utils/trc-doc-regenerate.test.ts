import { describe, expect, it } from 'vitest';
import {
	REGEN_POLL_LIMIT_MS,
	REGEN_TEXT,
	canRegenerate,
	initialRegenState,
	isRegenBusy,
	regenStatus,
	regenerateState,
	type RegenEvent,
	type RegenState
} from './trc-doc-regenerate';

const T0 = Date.parse('2026-10-14T12:00:00Z');
const FRESH = '2026-10-14T12:15:00+00:00';
const STALE = '2026-10-14T11:00:00+00:00';

const run = (...events: RegenEvent[]): RegenState =>
	events.reduce(regenerateState, initialRegenState());
const start: RegenEvent = { type: 'start' };
const regen = (status: number, body: unknown, now = T0): RegenEvent => ({
	type: 'regenerate',
	status,
	body,
	now
});
const meta = (status: number, body: unknown, now = T0): RegenEvent => ({
	type: 'meta',
	status,
	body,
	now
});
const ok = (rebuilt: string) => ({
	status: 'ok',
	kind: 'report',
	id: 'R'.repeat(32),
	expires_at: FRESH,
	rebuilt
});
const pending = { status: 'pending', kind: 'report', id: 'R'.repeat(32) };

describe('regenerateState', () => {
	it('starts idle with Regenerate available', () => {
		const s = initialRegenState();
		expect(s.phase).toBe('idle');
		expect(canRegenerate(s)).toBe(true);
		expect(isRegenBusy(s)).toBe(false);
	});

	it('shows Rebuilding… while the request is out, and ignores a second press', () => {
		const s = run(start);
		expect(s.phase).toBe('requesting');
		expect(s.message).toBe(REGEN_TEXT.working);
		expect(isRegenBusy(s)).toBe(true);
		expect(regenerateState(s, start)).toBe(s);
	});

	it('200 original_data: reloads meta, then says so and opens the viewer', () => {
		const reloading = run(start, regen(200, ok('original_data')));
		expect(reloading.phase).toBe('reloading');
		expect(reloading.open).toBe(false);
		const s = regenerateState(reloading, meta(200, { expires_at: FRESH }));
		expect(s.phase).toBe('rebuilt');
		expect(s.message).toBe(REGEN_TEXT.original);
		expect(s.expiresAt).toBe(FRESH);
		expect(s.open).toBe(true);
		expect(regenerateState(s, { type: 'opened' }).open).toBe(false);
	});

	it('200 current_data says it was rebuilt with current data', () => {
		const s = run(start, regen(200, ok('current_data')), meta(200, { expires_at: FRESH }));
		expect(s.message).toBe(REGEN_TEXT.current);
	});

	it('200 then a failed meta read is a retryable failure, not a silent success', () => {
		const s = run(start, regen(200, ok('original_data')), meta(503, null));
		expect(s.phase).toBe('failed');
		expect(s.message).toBe(REGEN_TEXT.failed);
		expect(canRegenerate(s)).toBe(true);
	});

	it('202: polls until meta shows a fresh copy, then opens it as current data', () => {
		const rebuilding = run(start, regen(202, pending));
		expect(rebuilding.phase).toBe('rebuilding');
		expect(rebuilding.message).toBe(REGEN_TEXT.working);
		expect(rebuilding.pollUntil).toBe(T0 + REGEN_POLL_LIMIT_MS);
		const still = regenerateState(rebuilding, meta(404, null, T0 + 3_000));
		expect(still).toBe(rebuilding);
		const transient = regenerateState(still, meta(0, null, T0 + 6_000));
		expect(transient.phase).toBe('rebuilding');
		const s = regenerateState(transient, meta(200, { expires_at: FRESH }, T0 + 9_000));
		expect(s.phase).toBe('rebuilt');
		expect(s.message).toBe(REGEN_TEXT.current);
		expect(s.open).toBe(true);
	});

	it('202: a meta answer with an old expiry is not the new copy yet', () => {
		const s = run(start, regen(202, pending), meta(200, { expires_at: STALE }, T0 + 3_000));
		expect(s.phase).toBe('rebuilding');
	});

	it('202: stops after five minutes and lets the user try again', () => {
		const s = run(start, regen(202, pending), meta(404, null, T0 + REGEN_POLL_LIMIT_MS));
		expect(s.phase).toBe('failed');
		expect(s.message).toBe(REGEN_TEXT.slow);
		expect(s.pollUntil).toBeNull();
		expect(canRegenerate(s)).toBe(true);
	});

	it('409 says it can no longer be rebuilt, and offers no retry', () => {
		const s = run(
			start,
			regen(409, { detail: { status: 'cannot_rebuild', reason: 'mapping_gone' } })
		);
		expect(s.phase).toBe('refused');
		expect(s.message).toBe(REGEN_TEXT.refused);
		expect(canRegenerate(s)).toBe(false);
	});

	it('404 says the document is gone, and offers no retry', () => {
		const s = run(start, regen(404, { detail: 'Document not found' }));
		expect(s.phase).toBe('gone');
		expect(s.message).toBe(REGEN_TEXT.gone);
		expect(canRegenerate(s)).toBe(false);
	});

	it.each([
		['a rate limit', 429, { detail: 'slow down' }],
		['an outage', 503, { detail: 'Document service unavailable' }],
		['a network failure', 0, null],
		['a 200 with the wrong body', 200, { status: 'weird' }],
		['a 202 with the wrong body', 202, {}]
	])('%s is a retryable failure', (_, status, body) => {
		const s = run(start, regen(status as number, body));
		expect(s.phase).toBe('failed');
		expect(s.message).toBe(REGEN_TEXT.failed);
		expect(canRegenerate(s)).toBe(true);
	});

	it('ignores answers that arrive in the wrong phase', () => {
		const idle = initialRegenState();
		expect(regenerateState(idle, meta(200, { expires_at: FRESH }))).toBe(idle);
		expect(regenerateState(idle, regen(200, ok('original_data')))).toBe(idle);
	});

	it('a rebuilt copy that expires in turn can be regenerated again', () => {
		const rebuilt = run(start, regen(200, ok('original_data')), meta(200, { expires_at: FRESH }));
		expect(canRegenerate(rebuilt)).toBe(true);
		expect(regenerateState(rebuilt, start).phase).toBe('requesting');
	});

	it('a remembered rebuild starts idle with its fresh expiry', () => {
		const s = initialRegenState(FRESH);
		expect(s.phase).toBe('idle');
		expect(s.expiresAt).toBe(FRESH);
	});
});

describe('regenStatus', () => {
	it('is null while idle, so the card shows its expiry text', () => {
		expect(regenStatus(initialRegenState(), true)).toBeNull();
	});
	it('shows progress and refusals', () => {
		expect(regenStatus(run(start), true)).toBe(REGEN_TEXT.working);
		const refused = run(
			start,
			regen(409, { detail: { status: 'cannot_rebuild', reason: 'no_recipe' } })
		);
		expect(regenStatus(refused, true)).toBe(REGEN_TEXT.refused);
	});
	it('says how it was rebuilt until that copy expires too', () => {
		const rebuilt = run(start, regen(200, ok('current_data')), meta(200, { expires_at: FRESH }));
		expect(regenStatus(rebuilt, false)).toBe(REGEN_TEXT.current);
		expect(regenStatus(rebuilt, true)).toBeNull();
	});
});
