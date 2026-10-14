import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { initMermaid } from '$lib/utils';

// Real Mermaid (no mock): this pins what Mermaid does with the config initMermaid hands it.
// Mermaid registers a window listener at import when a `document` exists, so it is imported
// once before the stub goes up; initMermaid's own dynamic import then gets the cached module.
beforeAll(async () => {
	await import('mermaid');
}, 120_000);

const REMOTE = 'https://attacker.invalid/x';
const diagram = (init: Record<string, unknown>) =>
	`%%{init: ${JSON.stringify(init)}}%%\nflowchart TD\n A-->B`;

let mermaid: Awaited<ReturnType<typeof initMermaid>>;

beforeEach(async () => {
	vi.stubGlobal('document', { documentElement: { classList: { contains: () => false } } });
	mermaid = await initMermaid();
});
afterEach(() => {
	vi.unstubAllGlobals();
});

describe('initMermaid secure keys', () => {
	it("keeps Mermaid's own secure list and adds the keys that can carry a remote url()", () => {
		const secure = mermaid.mermaidAPI.getSiteConfig().secure ?? [];
		expect(secure).toEqual(
			expect.arrayContaining([
				'secure',
				'securityLevel',
				'startOnLoad',
				'maxTextSize',
				'suppressErrorRendering',
				'maxEdges',
				'themeCSS',
				'fontFamily',
				'altFontFamily',
				'themeVariables'
			])
		);
	});

	it.each([
		['themeCSS', { themeCSS: `.node { background: url(${REMOTE}); }` }],
		['fontFamily', { fontFamily: `x url(${REMOTE})` }],
		['altFontFamily', { altFontFamily: `x url(${REMOTE})` }],
		['themeVariables', { themeVariables: { fontFamily: `x url(${REMOTE})` } }]
	])('an init directive cannot set %s', async (_, init) => {
		await mermaid.parse(diagram(init));
		const config = mermaid.mermaidAPI.getConfig();
		expect(config.themeCSS).toBeUndefined();
		expect(JSON.stringify(config)).not.toContain('attacker.invalid');
	});

	it('a directive still cannot lower the security level', async () => {
		await mermaid.parse(diagram({ securityLevel: 'loose' }));
		expect(mermaid.mermaidAPI.getConfig().securityLevel).toBe('strict');
	});

	it('still lets a directive set an ordinary key, so the checks above are not vacuous', async () => {
		await mermaid.parse(diagram({ theme: 'forest' }));
		expect(mermaid.mermaidAPI.getConfig().theme).toBe('forest');
	});
});
