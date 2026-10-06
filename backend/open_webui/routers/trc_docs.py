"""TRC document viewer proxy (trc-backend spec 2026-10-06-document-viewer).

The browser's only way to a TRC document's bytes. Same-origin, so no presigned storage
URL ever reaches the browser and the bucket needs no CORS. Two checks happen HERE before
anything is forwarded: the user is authenticated (`get_verified_user`) and owns `chat_id`
(Chats table). RAGnarok then repeats its own ownership/chat/expiry checks and answers 404
for every refusal. Ids, kinds and formats are validated against fixed shapes, so nothing
the browser chose is forwarded beyond them.

Logs carry user/chat/doc ids, kind, format, status and byte counts — never the bytes, a
title, or the service key.
"""

import logging
import re
from typing import Literal

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Response
from open_webui.config import RAGNAROK_BASE_URL, RAGNAROK_SERVICE_KEY
from open_webui.env import AIOHTTP_CLIENT_SESSION_SSL
from open_webui.models.chats import Chats
from open_webui.utils.auth import get_verified_user
from open_webui.utils.session_pool import get_session

log = logging.getLogger(__name__)

router = APIRouter()

_ID_SHAPES = {
    'list': re.compile(r'^lst_[A-Za-z0-9_-]{22}$'),
    'report': re.compile(r'^[A-Za-z0-9_-]{32}$'),
}
_MAX_BYTES = 20 * 1024 * 1024
_CHUNK_BYTES = 64 * 1024
_KIND_FORMATS = {
    'list': {'meta', 'csv', 'pdf'},
    'report': {'meta', 'md', 'pdf'},
}
_MEDIA_TYPES = {
    'csv': 'text/csv; charset=utf-8',
    'md': 'text/markdown; charset=utf-8',
    'pdf': 'application/pdf',
    'meta': 'application/json',
}
_TIMEOUT_SECONDS = 30
_DOWNLOAD_NAMES = {
    'csv': 'trc-list.csv',
    'pdf': 'trc-document.pdf',
    'md': 'trc-document.md',
    'meta': 'trc-document.json',
}


async def _read_capped(resp) -> bytes:
    """Read the whole body, refusing (502) as soon as it exceeds _MAX_BYTES."""
    too_large = HTTPException(status_code=502, detail='Document too large to display')
    if resp.content_length is not None and resp.content_length > _MAX_BYTES:
        raise too_large
    chunks = []
    total = 0
    async for chunk in resp.content.iter_chunked(_CHUNK_BYTES):
        total += len(chunk)
        if total > _MAX_BYTES:
            raise too_large
        chunks.append(chunk)
    return b''.join(chunks)


@router.get('/docs/{kind}/{doc_id}')
async def get_trc_doc(
    kind: Literal['list', 'report'],
    doc_id: str,
    chat_id: str,
    format: Literal['meta', 'csv', 'md', 'pdf'],
    download: bool = False,
    user=Depends(get_verified_user),
):
    if not (RAGNAROK_BASE_URL and RAGNAROK_SERVICE_KEY):
        raise HTTPException(status_code=503, detail='Document viewer is not configured')
    if not _ID_SHAPES[kind].fullmatch(doc_id):
        raise HTTPException(status_code=404, detail='Document not found')
    if format not in _KIND_FORMATS[kind]:
        raise HTTPException(status_code=404, detail='Document not found')
    chat = await Chats.get_chat_by_id_and_user_id(chat_id, user.id)
    if chat is None:
        raise HTTPException(status_code=404, detail='Document not found')

    url = f'{RAGNAROK_BASE_URL.rstrip("/")}/api/docs/{kind}/{doc_id}/content'
    payload = {'session_id': f'{user.id}:{chat_id}', 'user_id': user.id, 'format': format}
    headers = {'Authorization': f'Bearer {RAGNAROK_SERVICE_KEY}'}
    try:
        session = await get_session()
        async with session.post(
            url,
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=_TIMEOUT_SECONDS),
            ssl=AIOHTTP_CLIENT_SESSION_SSL,
        ) as resp:
            if resp.status == 404:
                raise HTTPException(status_code=404, detail='Document not found')
            if resp.status != 200:
                log.warning('trc_docs: backend status %s kind=%s fmt=%s', resp.status, kind, format)
                raise HTTPException(status_code=503, detail='Document service unavailable')
            body = await _read_capped(resp)
    except HTTPException:
        raise
    except (TimeoutError, aiohttp.ClientError) as exc:
        log.warning('trc_docs: backend unreachable (%s) kind=%s fmt=%s', type(exc).__name__, kind, format)
        raise HTTPException(status_code=503, detail='Document service unavailable')

    log.info('trc_docs: served user=%s chat=%s kind=%s fmt=%s bytes=%d', user.id, chat_id, kind, format, len(body))
    disposition = f'attachment; filename="{_DOWNLOAD_NAMES[format]}"' if download else 'inline'
    return Response(
        content=body,
        media_type=_MEDIA_TYPES[format],
        headers={
            'Cache-Control': 'no-store',
            'X-Content-Type-Options': 'nosniff',
            'Content-Disposition': disposition,
            'Content-Security-Policy': 'sandbox',
        },
    )
