"""Tests for the TRC document viewer proxy route (GET /api/v1/trc/docs/{kind}/{doc_id}).

The route function is invoked directly as a plain coroutine, with the chat lookup and the
RAGnarok session patched, so no live app, DB, or network is needed.
"""

import json
import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from fastapi import HTTPException

from open_webui.routers import trc_docs

LIST_ID = 'lst_' + 'A' * 22
REPORT_ID = 'B' * 32
KEY = 'sekret-service-key'
SECRET_BODY = b'Jane Invented,jane@example.invalid\n'
USER = SimpleNamespace(id='u1', role='user')


class FakeContent:
    def __init__(self, body: bytes, chunk: int = 3):
        self._body = body
        self._chunk = chunk

    async def iter_chunked(self, n: int):
        # Deliberately tiny chunks, whatever n is: a real stream hands over what is buffered.
        for i in range(0, len(self._body), self._chunk):
            yield self._body[i : i + self._chunk]


class FakeResponse:
    def __init__(self, status=200, body=SECRET_BODY, content_type='text/csv', content_length=None, chunk=3):
        self.status = status
        self.content_length = content_length
        self.headers = {'Content-Type': content_type}
        self.content = FakeContent(body, chunk)


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))

        @asynccontextmanager
        async def _cm():
            if self.error:
                raise self.error
            yield self.response

        return _cm()


def _patches(session, chat=object(), base='http://ragnarok.internal:8000/', key=KEY):
    return (
        patch.object(trc_docs.Chats, 'get_chat_by_id_and_user_id', new=AsyncMock(return_value=chat)),
        patch.object(trc_docs, 'get_session', new=AsyncMock(return_value=session)),
        patch.object(trc_docs, 'RAGNAROK_BASE_URL', base),
        patch.object(trc_docs, 'RAGNAROK_SERVICE_KEY', key),
    )


async def _call(session, kind='list', doc_id=LIST_ID, fmt='csv', download=False, **overrides):
    p1, p2, p3, p4 = _patches(session, **overrides)
    with p1, p2, p3, p4:
        return await trc_docs.get_trc_doc(
            kind=kind, doc_id=doc_id, chat_id='c1', format=fmt, download=download, user=USER
        )


class TestSuccess:
    @pytest.mark.asyncio
    async def test_serves_bytes_with_safe_headers_and_posts_expected_request(self):
        session = FakeSession(FakeResponse())
        resp = await _call(session)

        assert resp.body == SECRET_BODY
        assert resp.media_type == 'text/csv; charset=utf-8'
        assert resp.headers['content-type'] == 'text/csv; charset=utf-8'
        assert resp.headers['content-security-policy'] == 'sandbox'
        assert resp.headers['cache-control'] == 'no-store'
        assert resp.headers['x-content-type-options'] == 'nosniff'
        assert resp.headers['content-disposition'] == 'inline'

        assert len(session.calls) == 1
        url, kwargs = session.calls[0]
        assert url == f'http://ragnarok.internal:8000/api/docs/list/{LIST_ID}/content'
        assert kwargs['headers'] == {'Authorization': f'Bearer {KEY}'}
        assert kwargs['json'] == {'session_id': 'u1:c1', 'user_id': 'u1', 'format': 'csv'}

    @pytest.mark.asyncio
    async def test_download_sets_attachment_filename(self):
        resp = await _call(FakeSession(FakeResponse()), download=True)
        assert resp.headers['content-disposition'] == 'attachment; filename="trc-list.csv"'

    @pytest.mark.asyncio
    async def test_report_kind_uses_report_path(self):
        session = FakeSession(FakeResponse(content_type='application/pdf'))
        await _call(session, kind='report', doc_id=REPORT_ID, fmt='pdf', download=True)
        assert session.calls[0][0].endswith(f'/api/docs/report/{REPORT_ID}/content')


class TestRefusalsBeforeAnyPost:
    @pytest.mark.asyncio
    async def test_chat_not_owned_is_404(self):
        session = FakeSession(FakeResponse())
        with pytest.raises(HTTPException) as exc:
            await _call(session, chat=None)
        assert exc.value.status_code == 404
        assert session.calls == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'kind,doc_id',
        [
            ('list', REPORT_ID),
            ('report', LIST_ID),
            ('list', 'lst_short'),
            ('list', LIST_ID + '\n'),
            ('report', REPORT_ID + '\n'),
            ('list', '../etc/passwd'),
            ('report', 'B' * 31),
        ],
    )
    async def test_wrong_shape_id_is_404(self, kind, doc_id):
        session = FakeSession(FakeResponse())
        with pytest.raises(HTTPException) as exc:
            await _call(session, kind=kind, doc_id=doc_id)
        assert exc.value.status_code == 404
        assert session.calls == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize('overrides', [{'base': ''}, {'key': ''}, {'base': None}])
    async def test_unconfigured_is_503(self, overrides):
        session = FakeSession(FakeResponse())
        with pytest.raises(HTTPException) as exc:
            await _call(session, **overrides)
        assert exc.value.status_code == 503
        assert session.calls == []


class TestBackendFailures:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'status,expected',
        [(404, 404), (500, 503), (429, 503), (401, 503)],
    )
    async def test_status_mapping(self, status, expected):
        with pytest.raises(HTTPException) as exc:
            await _call(FakeSession(FakeResponse(status=status)))
        assert exc.value.status_code == expected

    @pytest.mark.asyncio
    @pytest.mark.parametrize('error', [aiohttp.ClientError('boom'), TimeoutError()])
    async def test_transport_errors_are_503(self, error):
        with pytest.raises(HTTPException) as exc:
            await _call(FakeSession(error=error))
        assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_multi_chunk_body_is_served_whole(self):
        body = bytes(range(256)) * 40
        resp = await _call(FakeSession(FakeResponse(body=body)))
        assert resp.body == body

    @pytest.mark.asyncio
    async def test_oversize_streamed_body_is_502(self):
        big = b'x' * (trc_docs._MAX_BYTES + 1)
        with pytest.raises(HTTPException) as exc:
            await _call(FakeSession(FakeResponse(body=big, chunk=1024 * 1024)))
        assert exc.value.status_code == 502

    @pytest.mark.asyncio
    async def test_oversize_declared_length_is_502_without_reading(self):
        resp = FakeResponse(content_length=trc_docs._MAX_BYTES + 1)
        resp.content.iter_chunked = None  # would raise if the body were touched
        with pytest.raises(HTTPException) as exc:
            await _call(FakeSession(resp))
        assert exc.value.status_code == 502

    @pytest.mark.asyncio
    async def test_body_at_cap_is_served(self):
        body = b'x' * trc_docs._MAX_BYTES
        resp = await _call(FakeSession(FakeResponse(body=body, chunk=1024 * 1024)))
        assert len(resp.body) == trc_docs._MAX_BYTES


class TestContentType:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'kind,doc_id,fmt,expected',
        [
            ('list', LIST_ID, 'csv', 'text/csv; charset=utf-8'),
            ('report', REPORT_ID, 'md', 'text/markdown; charset=utf-8'),
            ('list', LIST_ID, 'pdf', 'application/pdf'),
            ('report', REPORT_ID, 'meta', 'application/json'),
        ],
    )
    async def test_backend_content_type_is_ignored(self, kind, doc_id, fmt, expected):
        session = FakeSession(FakeResponse(content_type='text/html'))
        resp = await _call(session, kind=kind, doc_id=doc_id, fmt=fmt)
        assert resp.headers['content-type'] == expected
        assert resp.headers['content-security-policy'] == 'sandbox'


class TestKindFormatMismatch:
    @pytest.mark.asyncio
    @pytest.mark.parametrize('kind,doc_id,fmt', [('list', LIST_ID, 'md'), ('report', REPORT_ID, 'csv')])
    async def test_mismatch_is_404_without_backend_call(self, kind, doc_id, fmt):
        session = FakeSession(FakeResponse())
        with pytest.raises(HTTPException) as exc:
            await _call(session, kind=kind, doc_id=doc_id, fmt=fmt)
        assert exc.value.status_code == 404
        assert session.calls == []


class TestLogHygiene:
    @pytest.mark.asyncio
    async def test_logs_never_contain_key_or_body(self, caplog):
        caplog.set_level(logging.DEBUG)
        await _call(FakeSession(FakeResponse()))
        for status in (404, 500):
            with pytest.raises(HTTPException):
                await _call(FakeSession(FakeResponse(status=status)))
        with pytest.raises(HTTPException):
            await _call(FakeSession(error=aiohttp.ClientError(f'bad http://u:{KEY}@h/')))

        text = caplog.text
        assert 'trc_docs' in text
        assert KEY not in text
        assert 'Jane Invented' not in text
        assert 'jane@example.invalid' not in text


# ---------------------------------------------------------------------------------------
# POST /api/v1/trc/docs/{kind}/{doc_id}/regenerate (contract C4)
# ---------------------------------------------------------------------------------------

OK_BODY = {
    'status': 'ok',
    'kind': 'list',
    'id': LIST_ID,
    'expires_at': '2026-10-14T12:15:00+00:00',
    'rebuilt': 'current_data',
}


def _json(data, status=200, **kw):
    return FakeResponse(status=status, body=json.dumps(data).encode('utf-8'), content_type='application/json', **kw)


async def _regen(session, kind='list', doc_id=LIST_ID, **overrides):
    p1, p2, p3, p4 = _patches(session, **overrides)
    with p1, p2, p3, p4:
        return await trc_docs.regenerate_trc_doc(kind=kind, doc_id=doc_id, chat_id='c1', user=USER)


def _body(resp):
    return json.loads(resp.body)


class TestRegenerateForwarding:
    @pytest.mark.asyncio
    async def test_posts_identity_from_the_session_with_the_service_key(self):
        session = FakeSession(_json(OK_BODY))
        await _regen(session)

        assert len(session.calls) == 1
        url, kwargs = session.calls[0]
        assert url == f'http://ragnarok.internal:8000/api/docs/list/{LIST_ID}/regenerate'
        assert kwargs['headers'] == {'Authorization': f'Bearer {KEY}'}
        assert kwargs['json'] == {'session_id': 'u1:c1', 'user_id': 'u1'}

    @pytest.mark.asyncio
    async def test_200_passes_the_contract_body_through(self):
        resp = await _regen(FakeSession(_json(OK_BODY)))
        assert resp.status_code == 200
        assert _body(resp) == OK_BODY
        assert resp.headers['cache-control'] == 'no-store'

    @pytest.mark.asyncio
    async def test_200_keeps_only_contract_keys(self):
        noisy = {**OK_BODY, 'title': 'Synthetic Holdings Ltd', 'object_key': 'reports/abc.pdf'}
        resp = await _regen(FakeSession(_json(noisy)))
        assert _body(resp) == OK_BODY

    @pytest.mark.asyncio
    async def test_202_pending_for_a_report(self):
        resp = await _regen(
            FakeSession(_json({'status': 'pending', 'kind': 'report', 'id': REPORT_ID}, status=202)),
            kind='report',
            doc_id=REPORT_ID,
        )
        assert resp.status_code == 202
        assert _body(resp) == {'status': 'pending', 'kind': 'report', 'id': REPORT_ID}

    @pytest.mark.asyncio
    @pytest.mark.parametrize('reason', ['no_recipe', 'mapping_gone', 'render_failed'])
    async def test_409_cannot_rebuild_passes_through(self, reason):
        body = {'detail': {'status': 'cannot_rebuild', 'reason': reason}}
        resp = await _regen(FakeSession(_json(body, status=409)))
        assert resp.status_code == 409
        assert _body(resp) == body


class TestRegenerateRefusals:
    @pytest.mark.asyncio
    async def test_chat_not_owned_is_404_without_any_post(self):
        session = FakeSession(_json(OK_BODY))
        with pytest.raises(HTTPException) as exc:
            await _regen(session, chat=None)
        assert exc.value.status_code == 404
        assert session.calls == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'kind,doc_id',
        [('list', REPORT_ID), ('report', LIST_ID), ('list', '../etc/passwd'), ('report', REPORT_ID + '\n')],
    )
    async def test_wrong_shape_id_is_404_without_any_post(self, kind, doc_id):
        session = FakeSession(_json(OK_BODY))
        with pytest.raises(HTTPException) as exc:
            await _regen(session, kind=kind, doc_id=doc_id)
        assert exc.value.status_code == 404
        assert session.calls == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize('overrides', [{'base': ''}, {'key': ''}, {'base': None}])
    async def test_unconfigured_is_503(self, overrides):
        session = FakeSession(_json(OK_BODY))
        with pytest.raises(HTTPException) as exc:
            await _regen(session, **overrides)
        assert exc.value.status_code == 503
        assert session.calls == []


class TestRegenerateBackendAnswers:
    @pytest.mark.asyncio
    async def test_backend_404_is_404(self):
        """Unknown id, another user's document or another chat's: one answer for all."""
        with pytest.raises(HTTPException) as exc:
            await _regen(FakeSession(_json({'detail': 'document not found'}, status=404)))
        assert exc.value.status_code == 404
        assert exc.value.detail == 'Document not found'

    @pytest.mark.asyncio
    async def test_backend_429_is_429(self):
        with pytest.raises(HTTPException) as exc:
            await _regen(FakeSession(_json({'detail': 'rate limited'}, status=429)))
        assert exc.value.status_code == 429

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        'status,data',
        [
            (500, {'detail': 'Internal Server Error'}),
            (401, {'detail': 'bad credential'}),
            (200, {'status': 'ok'}),
            (200, {**OK_BODY, 'rebuilt': 'something_else'}),
            (202, {'status': 'ok'}),
            (409, {'detail': {'status': 'cannot_rebuild', 'reason': 'brand_new_reason'}}),
            (409, {'detail': 'conflict'}),
            (200, ['not', 'an', 'object']),
        ],
    )
    async def test_anything_off_contract_is_503_never_500(self, status, data):
        with pytest.raises(HTTPException) as exc:
            await _regen(FakeSession(_json(data, status=status)))
        assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_non_json_body_is_503(self):
        resp = FakeResponse(status=200, body=b'<html>oops</html>', content_type='text/html')
        with pytest.raises(HTTPException) as exc:
            await _regen(FakeSession(resp))
        assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_oversize_body_is_503(self):
        big = _json(OK_BODY, content_length=trc_docs._REGENERATE_MAX_BYTES + 1)
        with pytest.raises(HTTPException) as exc:
            await _regen(FakeSession(big))
        assert exc.value.status_code == 503

    @pytest.mark.asyncio
    @pytest.mark.parametrize('error', [aiohttp.ClientError('boom'), TimeoutError()])
    async def test_transport_errors_are_503(self, error):
        with pytest.raises(HTTPException) as exc:
            await _regen(FakeSession(error=error))
        assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_logs_never_contain_the_key(self, caplog):
        caplog.set_level(logging.DEBUG)
        await _regen(FakeSession(_json(OK_BODY)))
        with pytest.raises(HTTPException):
            await _regen(FakeSession(error=aiohttp.ClientError(f'bad http://u:{KEY}@h/')))
        assert 'trc_docs: regenerate' in caplog.text
        assert KEY not in caplog.text
