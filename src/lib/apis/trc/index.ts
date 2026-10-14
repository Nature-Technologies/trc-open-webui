/**
 * The TRC document routes the card talks to directly (contract C4). Both helpers answer
 * `{ status, body }` and never throw — a network failure is status 0 — because the card
 * hands every answer, failures included, to regenerateState in $lib/utils/trc-doc-regenerate.
 */
import { trcDocRegenerateUrl, trcDocUrl, type TrcDocCardData } from '$lib/utils/trc-doc';

type DocRef = Pick<TrcDocCardData, 'kind' | 'id'>;

/** An HTTP answer as the card consumes it. `status` 0 means none arrived. */
export type TrcDocReply = { status: number; body: unknown };

const send = async (url: string, init: RequestInit): Promise<TrcDocReply> => {
	try {
		const res = await fetch(url, { credentials: 'include', ...init });
		let body: unknown = null;
		try {
			body = await res.json();
		} catch {
			body = null;
		}
		return { status: res.status, body };
	} catch {
		return { status: 0, body: null };
	}
};

/** Rebuild an expired document in place: `POST /api/v1/trc/docs/{kind}/{id}/regenerate`. */
export const regenerateTrcDoc = (token: string, doc: DocRef, chatId: string) =>
	send(trcDocRegenerateUrl(doc, chatId), {
		method: 'POST',
		headers: { Accept: 'application/json', authorization: `Bearer ${token}` }
	});

/** One document's meta (title, counts, formats, expiry) from the viewer route. */
export const getTrcDocMeta = (token: string, doc: DocRef, chatId: string) =>
	send(trcDocUrl(doc, chatId, 'meta'), {
		method: 'GET',
		headers: { Accept: 'application/json', authorization: `Bearer ${token}` }
	});
