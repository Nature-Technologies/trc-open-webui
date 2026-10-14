/**
 * Prepend a Content-Security-Policy <meta> tag to HTML.
 * First CSP meta tag wins per spec, so any existing CSP
 * in the HTML is effectively overridden.
 */
export function injectCsp(html: string, csp: string): string {
	if (!csp) return html;
	const escaped = csp.replace(/"/g, '&quot;');
	const tag = `<meta http-equiv="Content-Security-Policy" content="${escaped}">`;
	const idx = html.indexOf('<head>');
	return idx !== -1 ? html.slice(0, idx + 6) + tag + html.slice(idx + 6) : tag + html;
}

/**
 * The policy an SVG artifact is framed behind when the deployment configures no IFRAME_CSP:
 * no script, no fetch, no external image/font/media/stylesheet, no nested frame, no form
 * post, no <base>; inline styles and data:/blob: media only.
 */
export const FALLBACK_IFRAME_CSP =
	"default-src 'none'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; " +
	"media-src data: blob:; form-action 'none'; base-uri 'none'";

/**
 * A standalone document for a model-written ```svg block, behind the CSP. An SVG put into the
 * page itself loads whatever its <image href> or style url() names, outside every CSP; framed
 * with a CSP meta (the configured one, else the strict fallback) and a script-less sandbox it
 * cannot.
 */
export function svgArtifactDocument(svg: string, csp: string): string {
	const doc =
		'<!doctype html><html><head><meta charset="utf-8">' +
		'<style>html,body{margin:0;height:100%}body{display:flex;align-items:center;justify-content:center}' +
		'svg{max-width:100%;max-height:100%}</style></head>' +
		`<body>${svg}</body></html>`;
	return injectCsp(doc, csp || FALLBACK_IFRAME_CSP);
}
