"""TRC document viewer proxy (trc-backend spec 2026-10-06-document-viewer).

The browser's only way to a TRC document's bytes. Same-origin, so no presigned storage
URL ever reaches the browser and the bucket needs no CORS. Two checks happen HERE before
anything is forwarded: the user is authenticated (`get_verified_user`) and owns `chat_id`
(Chats table). RAGnarok then repeats its own ownership/chat/expiry checks and answers 404
for every refusal. Ids, kinds and formats are validated against fixed shapes, so nothing
the browser chose is forwarded beyond them.

It also proxies Regenerate (contract C4, `POST .../regenerate`): the same two checks,
then RAGnarok rebuilds the document in place under the same id. Only the contract's keys
travel back, and anything off-contract becomes 503, so the browser never sees a 500.

Logs carry user/chat/doc ids, kind, format, status and byte counts — never the bytes, a
title, or the service key.
"""

import json
import logging
import re
from typing import Literal

import aiohttp
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import JSONResponse
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
# Regenerate (contract C4). A list or a render_report rebuild answers synchronously, so
# it gets longer than a byte fetch; a generate_report rebuild answers 202 at once.
_REGENERATE_TIMEOUT_SECONDS = 60
# The answer is a few ids and a timestamp; anything bigger is not a contract answer.
_REGENERATE_MAX_BYTES = 64 * 1024
_REBUILT = {'original_data', 'current_data'}
_CANNOT_REBUILD_REASONS = {'no_recipe', 'mapping_gone', 'render_failed'}


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


async def _read_json(resp):
    """The body as JSON, or None when it is over _REGENERATE_MAX_BYTES or not JSON."""
    if resp.content_length is not None and resp.content_length > _REGENERATE_MAX_BYTES:
        return None
    chunks = []
    total = 0
    async for chunk in resp.content.iter_chunked(_CHUNK_BYTES):
        total += len(chunk)
        if total > _REGENERATE_MAX_BYTES:
            return None
        chunks.append(chunk)
    try:
        return json.loads(b''.join(chunks))
    except (ValueError, RecursionError):
        # RecursionError: a deeply nested body fits under the size cap and json.loads raises it.
        return None


def _regenerate_body(status: int, kind: str, doc_id: str, data) -> dict | None:
    """The C4 body for a backend answer, rebuilt from known keys only, or None.

    Only these keys ever reach the browser, so a backend change can never widen what the
    card sees. `kind` and `id` come from the validated request, not from the backend.
    """
    if not isinstance(data, dict):
        return None
    if status == 200 and data.get('status') == 'ok':
        expires_at, rebuilt = data.get('expires_at'), data.get('rebuilt')
        if isinstance(expires_at, str) and rebuilt in _REBUILT:
            return {'status': 'ok', 'kind': kind, 'id': doc_id, 'expires_at': expires_at, 'rebuilt': rebuilt}
        return None
    if status == 202 and data.get('status') == 'pending':
        return {'status': 'pending', 'kind': kind, 'id': doc_id}
    if status == 409:
        detail = data.get('detail')
        if (
            isinstance(detail, dict)
            and detail.get('status') == 'cannot_rebuild'
            and detail.get('reason') in _CANNOT_REBUILD_REASONS
        ):
            return {'detail': {'status': 'cannot_rebuild', 'reason': detail['reason']}}
    return None


@router.post('/docs/{kind}/{doc_id}/regenerate')
async def regenerate_trc_doc(
    kind: Literal['list', 'report'],
    doc_id: str,
    chat_id: str,
    user=Depends(get_verified_user),
):
    """Rebuild an expired document in place (contract C4), with no model turn.

    Same gate as the GET above: an authenticated user who owns `chat_id`, an id of the
    kind's shape. Identity is the session's, never the request's: `session_id` and
    `user_id` are built here from `user.id`. RAGnarok repeats the owner + chat check and
    answers 404 for every refusal; this route forwards 200, 202, 404, 409 and 429 and
    turns anything else into 503, so the card never sees a 500.
    """
    if not (RAGNAROK_BASE_URL and RAGNAROK_SERVICE_KEY):
        raise HTTPException(status_code=503, detail='Document viewer is not configured')
    if not _ID_SHAPES[kind].fullmatch(doc_id):
        raise HTTPException(status_code=404, detail='Document not found')
    chat = await Chats.get_chat_by_id_and_user_id(chat_id, user.id)
    if chat is None:
        raise HTTPException(status_code=404, detail='Document not found')

    url = f'{RAGNAROK_BASE_URL.rstrip("/")}/api/docs/{kind}/{doc_id}/regenerate'
    payload = {'session_id': f'{user.id}:{chat_id}', 'user_id': user.id}
    headers = {'Authorization': f'Bearer {RAGNAROK_SERVICE_KEY}'}
    try:
        session = await get_session()
        async with session.post(
            url,
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=_REGENERATE_TIMEOUT_SECONDS),
            ssl=AIOHTTP_CLIENT_SESSION_SSL,
        ) as resp:
            status = resp.status
            data = await _read_json(resp) if status in (200, 202, 409) else None
    except (TimeoutError, aiohttp.ClientError) as exc:
        log.warning('trc_docs: regenerate unreachable (%s) kind=%s doc=%s', type(exc).__name__, kind, doc_id)
        raise HTTPException(status_code=503, detail='Document service unavailable')

    if status == 404:
        raise HTTPException(status_code=404, detail='Document not found')
    if status == 429:
        raise HTTPException(status_code=429, detail='Too many document requests; try again shortly')
    body = _regenerate_body(status, kind, doc_id, data)
    if body is None:
        log.warning('trc_docs: regenerate backend status %s kind=%s doc=%s', status, kind, doc_id)
        raise HTTPException(status_code=503, detail='Document service unavailable')

    log.info('trc_docs: regenerate user=%s chat=%s kind=%s doc=%s status=%s', user.id, chat_id, kind, doc_id, status)
    return JSONResponse(status_code=status, content=body, headers={'Cache-Control': 'no-store'})
