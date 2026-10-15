<script lang="ts">
	import DOMPurify from 'dompurify';
	import type { Token } from 'marked';

	import { WEBUI_BASE_URL } from '$lib/constants';
	import { settings } from '$lib/stores';

	export let id: string;
	export let token: Token;

	let html: string | null = null;

	$: text = token.type === 'html' ? token?.text : null;
	$: html = text ? DOMPurify.sanitize(text) : null;
</script>

{#if token.type === 'html'}
	{#if html && /<\/?video/i.test(html)}
		<!-- TRC: a message cannot make the browser load media or frames. A <video>, <audio> or
		     <iframe> in message content renders nothing (and not its own markup as text either);
		     the backend's own <file type="html"> and <status> tags are handled below. -->
	{:else if html && /<\/?audio/i.test(html)}{:else if token.text && /<\/?iframe/i.test(token.text)}{:else if token.text && token.text.includes('<status')}
		{@const match = token.text.match(/<status title="([^"]+)" done="(true|false)" ?\/?>/)}
		{@const statusTitle = match && match[1]}
		{@const statusDone = match && match[2] === 'true'}
		{#if statusTitle}
			<div class="flex flex-col justify-center -space-y-0.5">
				<div
					class="{statusDone === false
						? 'shimmer'
						: ''} text-gray-500 dark:text-gray-500 line-clamp-1 text-wrap"
				>
					{statusTitle}
				</div>
			</div>
		{:else}
			{token.text}
		{/if}
	{:else if token.text.includes(`<file type="html"`)}
		{@const match = token.text.match(/<file type="html" id="([^"]+)"/)}
		{@const fileId = match && match[1]}
		{#if fileId}
			<iframe
				class="w-full my-2"
				src={`${WEBUI_BASE_URL}/api/v1/files/${fileId}/content/html`}
				title="Content"
				frameborder="0"
				sandbox="allow-scripts allow-downloads{($settings?.iframeSandboxAllowForms ?? false)
					? ' allow-forms'
					: ''}{($settings?.iframeSandboxAllowSameOrigin ?? false) ? ' allow-same-origin' : ''}"
				referrerpolicy="strict-origin-when-cross-origin"
				allowfullscreen
				width="100%"
				on:load={(e) => {
					try {
						e.currentTarget.style.height =
							e.currentTarget.contentWindow.document.body.scrollHeight + 20 + 'px';
					} catch {}
				}}
			></iframe>
		{/if}
	{:else if token.text.trim().match(/^<br\s*\/?>$/i)}
		<br />
	{:else}
		{token.text}
	{/if}
{/if}
