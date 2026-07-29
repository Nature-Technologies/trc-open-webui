"""Best-effort notifications to the RAGnarok backend when chats are deleted.

RAGnarok (this fork's companion service) masks PII in chat messages and
stores the token<->real-value mappings keyed by "<user_id>:<chat_id>". When
a chat -- or every chat belonging to a user -- is deleted here, telling
RAGnarok lets it purge those mappings immediately instead of waiting for its
own reconciling sweep. That sweep is the source of truth and already does
this on its own (default interval: 60 minutes); this module is only a
low-latency assist.

Every function here is fire-and-forget: it must never raise, block, or
meaningfully delay the deletion path that calls it. Any failure -- unset
configuration, a timeout, a connection error, a non-2xx response -- is
logged at warning level (ids and counts only, never PII, a chat title, or
the service key) and swallowed.
"""

import logging

import aiohttp
from open_webui.config import RAGNAROK_BASE_URL, RAGNAROK_SERVICE_KEY
from open_webui.env import AIOHTTP_CLIENT_SESSION_SSL
from open_webui.utils.session_pool import get_session

log = logging.getLogger(__name__)

# Kept short and well under a caller's own request timeout, so a slow or
# unreachable RAGnarok never turns into a slow chat deletion.
_REQUEST_TIMEOUT_SECONDS = 5


def _is_configured() -> bool:
    return bool(RAGNAROK_BASE_URL and RAGNAROK_SERVICE_KEY)


def log_startup_status() -> None:
    """Log once, at startup, whether RAGnarok chat-deletion notifications are enabled.

    Called from the app lifespan instead of from the notify functions below,
    so an unconfigured deployment gets one line at boot rather than a
    warning on every chat deletion.
    """
    if _is_configured():
        log.info('RAGnarok chat-deletion notifications enabled (base_url=%s)', RAGNAROK_BASE_URL)
    else:
        log.info(
            'RAGNAROK_BASE_URL / RAGNAROK_SERVICE_KEY not set; chat-deletion notifications to RAGnarok are disabled.'
        )


async def _notify(path: str, payload: dict) -> None:
    if not _is_configured():
        return

    url = f'{RAGNAROK_BASE_URL.rstrip("/")}{path}'
    headers = {'Authorization': f'Bearer {RAGNAROK_SERVICE_KEY}'}

    try:
        session = await get_session()
        async with session.post(
            url,
            json=payload,
            headers=headers,
            ssl=AIOHTTP_CLIENT_SESSION_SSL,
            timeout=aiohttp.ClientTimeout(total=_REQUEST_TIMEOUT_SECONDS),
        ) as response:
            if response.status >= 400:
                log.warning('RAGnarok notification to %s returned HTTP %d', path, response.status)
    except Exception as e:
        log.warning('RAGnarok notification to %s failed: %s', path, e)


async def notify_chat_deleted(user_id: str, chat_id: str) -> None:
    """Tell RAGnarok that a single chat was deleted, so it can purge that chat's PII mappings."""
    await _notify('/api/redaction/forget', {'conversation_key': f'{user_id}:{chat_id}'})


async def notify_user_chats_deleted(user_id: str) -> None:
    """Tell RAGnarok that every chat belonging to user_id was deleted."""
    await _notify('/api/redaction/forget-user', {'user_id': user_id})
