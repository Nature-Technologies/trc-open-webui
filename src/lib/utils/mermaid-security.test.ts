import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Mermaid needs a browser; it is replaced with a recorder so the test can see exactly how
// the app configures it.
const { initialize } = vi.hoisted(() => ({ initialize: vi.fn() }));
vi.mock('mermaid', () => ({ default: { initialize } }));

import { initMermaid } from '$lib/utils';

describe('initMermaid', () => {
	beforeEach(() => {
		initialize.mockClear();
		vi.stubGlobal('document', { documentElement: { classList: { contains: () => false } } });
	});
	afterEach(() => vi.unstubAllGlobals());

	it('runs mermaid at the strict security level', async () => {
		await initMermaid();
		expect(initialize).toHaveBeenCalledTimes(1);
		expect(initialize.mock.calls[0][0].securityLevel).toBe('strict');
	});

	it('keeps render-API mode and plain-text labels', async () => {
		await initMermaid();
		expect(initialize.mock.calls[0][0]).toMatchObject({ startOnLoad: false, htmlLabels: false });
	});
});
