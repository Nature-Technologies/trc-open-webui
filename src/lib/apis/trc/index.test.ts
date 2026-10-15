import { afterEach, describe, expect, it, vi } from 'vitest';
import { getTrcDocMeta, regenerateTrcDoc } from './index';

const LIST = 'lst_' + 'A'.repeat(22);
const REPORT = 'R'.repeat(32);

afterEach(() => {
	vi.unstubAllGlobals();
});

const lastCall = (fetchMock: { mock: { calls: unknown[] } }) =>
	fetchMock.mock.calls.at(-1) as unknown as [string, RequestInit];

describe('regenerateTrcDoc', () => {
	it('POSTs the fork route with the bearer token and returns status and JSON', async () => {
		const fetchMock = vi.fn(
			async () => new Response(JSON.stringify({ status: 'pending' }), { status: 202 })
		);
		vi.stubGlobal('fetch', fetchMock);

		const reply = await regenerateTrcDoc('tok', { kind: 'report', id: REPORT }, 'c1');

		expect(reply).toEqual({ status: 202, body: { status: 'pending' } });
		const [url, init] = lastCall(fetchMock);
		expect(url).toContain(`/api/v1/trc/docs/report/${REPORT}/regenerate?chat_id=c1`);
		expect(init.method).toBe('POST');
		expect((init.headers as Record<string, string>).authorization).toBe('Bearer tok');
	});

	it('answers status 0 instead of throwing when the network fails', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => Promise.reject(new TypeError('offline')))
		);
		expect(await regenerateTrcDoc('tok', { kind: 'list', id: LIST }, 'c1')).toEqual({
			status: 0,
			body: null
		});
	});

	it('answers a null body when the reply is not JSON', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => new Response('<html>', { status: 502 }))
		);
		expect(await regenerateTrcDoc('tok', { kind: 'list', id: LIST }, 'c1')).toEqual({
			status: 502,
			body: null
		});
	});
});

describe('getTrcDocMeta', () => {
	it('GETs the meta format of the viewer route', async () => {
		const fetchMock = vi.fn(
			async () => new Response(JSON.stringify({ expires_at: 'x' }), { status: 200 })
		);
		vi.stubGlobal('fetch', fetchMock);

		const reply = await getTrcDocMeta('tok', { kind: 'list', id: LIST }, 'c1');

		expect(reply).toEqual({ status: 200, body: { expires_at: 'x' } });
		const [url, init] = lastCall(fetchMock);
		expect(url).toContain(`/api/v1/trc/docs/list/${LIST}?`);
		expect(url).toContain('format=meta');
		expect(init.method).toBe('GET');
	});
});
