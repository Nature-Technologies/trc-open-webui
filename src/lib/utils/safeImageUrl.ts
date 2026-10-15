import { WEBUI_BASE_URL } from '$lib/constants';

const PLACEHOLDER_IMAGE = '/favicon.png';

// A path that stays on this origin: one leading slash. "//host" and "/\host" are
// protocol-relative URLs that name another host.
const isSameOriginPath = (url: string) => url.startsWith('/') && !/^\/[\\/]/.test(url);

// The configured backend origin, matched on a boundary so "https://app.example.evil.invalid"
// is not taken for "https://app.example".
const isUnderBaseUrl = (url: string) =>
	!!WEBUI_BASE_URL &&
	url.startsWith(WEBUI_BASE_URL) &&
	(url.length === WEBUI_BASE_URL.length || /^[/?#]/.test(url.slice(WEBUI_BASE_URL.length)));

/**
 * Validates an image URL against an allowlist of safe patterns and returns
 * the URL if trusted, or a placeholder otherwise.
 *
 * Allowed patterns:
 *   - Relative paths (starting with a single '/')
 *   - data:image/* URIs and blob: URLs
 *   - Same-origin URLs (starting with WEBUI_BASE_URL)
 *   - Gravatar URLs (https://www.gravatar.com/avatar/)
 *   - External HTTP(S) URLs when allowExternal is true
 *
 * All other URLs (including arbitrary http(s):// origins by default) are
 * rejected to prevent client-side IP/UA/Referer leaks to attacker-controlled servers.
 */
export function safeImageUrl(url: string, allowExternal = false): string {
	if (!url || url === '') {
		return `${WEBUI_BASE_URL}${PLACEHOLDER_IMAGE}`;
	}

	if (
		isUnderBaseUrl(url) ||
		url.startsWith('https://www.gravatar.com/avatar/') ||
		(allowExternal && /^https?:\/\//i.test(url)) ||
		/^(data|blob):/i.test(url) ||
		isSameOriginPath(url)
	) {
		return url;
	}

	return `${WEBUI_BASE_URL}${PLACEHOLDER_IMAGE}`;
}

// Resolves a relative URL; anything that comes back on this host was relative to the app.
// ".invalid" can never be a real host, so no absolute URL can pass for it.
const SELF = 'http://self.invalid';

const appOrigins = (): string[] => {
	const origins: string[] = [];
	if (typeof window !== 'undefined' && window.location?.origin)
		origins.push(window.location.origin);
	if (WEBUI_BASE_URL) {
		try {
			origins.push(new URL(WEBUI_BASE_URL).origin);
		} catch {
			// a malformed base URL trusts nothing extra
		}
	}
	return origins;
};

/**
 * The src a chat MESSAGE may give an image, or null when it must not load.
 *
 * A message is model output over restored client data, and an image URL in it is a request
 * the browser makes on its own, carrying whatever the model put in the URL to a host the
 * model chose. So only this app's own origin (a relative path or an absolute URL on it),
 * data:image/* and blob: URLs pass; every other host, scheme and protocol-relative form is
 * refused, and the caller shows the alt text instead.
 */
export function messageImageSrc(
	href: string | null | undefined,
	origins: string[] = appOrigins()
): string | null {
	const raw = (href ?? '').trim();
	if (!raw) return null;
	if (/^data:image\//i.test(raw) || /^blob:/i.test(raw)) return raw;

	let url: URL;
	try {
		url = new URL(raw, SELF);
	} catch {
		return null;
	}
	if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
	return url.origin === SELF || origins.includes(url.origin) ? raw : null;
}
