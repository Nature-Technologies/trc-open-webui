import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Mermaid and DOMPurify need a browser; both are replaced with recorders so the test can
// see exactly how the app configures them.
const { initialize, sanitize } = vi.hoisted(() => ({
	initialize: vi.fn(),
	sanitize: vi.fn((svg: string, _options: Record<string, any>) => svg)
}));
vi.mock('mermaid', () => ({ default: { initialize } }));
vi.mock('dompurify', () => ({ default: { sanitize } }));

import { initMermaid, sanitizeSvg } from '$lib/utils';

describe('initMermaid', () => {
	beforeEach(() => {
		initialize.mockClear();
		vi.stubGlobal('document', { documentElement: { classList: { contains: () => false } } });
	});
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('runs mermaid at the strict security level', async () => {
		await initMermaid();
		expect(initialize).toHaveBeenCalledTimes(1);
		expect(initialize.mock.calls[0][0].securityLevel).toBe('strict');
	});

	it('stops a diagram directive setting the keys that can carry a remote url()', async () => {
		await initMermaid();
		expect(initialize.mock.calls[0][0].secure).toEqual(
			expect.arrayContaining(['themeCSS', 'fontFamily', 'altFontFamily', 'themeVariables'])
		);
	});

	it('keeps render-API mode and plain-text labels', async () => {
		await initMermaid();
		expect(initialize.mock.calls[0][0]).toMatchObject({ startOnLoad: false, htmlLabels: false });
	});
});

describe('sanitizeSvg', () => {
	beforeEach(() => {
		sanitize.mockClear();
	});

	it('forbids every href on mermaid output', () => {
		sanitizeSvg('<svg></svg>');
		const options = sanitize.mock.calls[0][1];
		expect(options.FORBID_ATTR).toEqual(expect.arrayContaining(['href', 'xlink:href']));
		expect(options.ADD_ATTR).not.toContain('href');
		expect(options.ADD_ATTR).not.toContain('xlink:href');
	});

	it('still sanitises as SVG and returns what the sanitiser returns', () => {
		expect(sanitizeSvg('<svg><g/></svg>')).toBe('<svg><g/></svg>');
		expect(sanitize.mock.calls[0][1].USE_PROFILES).toEqual({ svg: true, svgFilters: true });
	});
});
