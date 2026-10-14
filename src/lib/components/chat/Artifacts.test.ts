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
	return { attrs, sandbox: (attrs.sandbox ?? '').split(/\s+/).filter(Boolean) };
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
