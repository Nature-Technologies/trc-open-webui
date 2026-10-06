"""Tests for the TRC document viewer proxy route (GET /api/v1/trc/docs/{kind}/{doc_id}).

The route function is invoked directly as a plain coroutine, with the chat lookup and the
RAGnarok session patched, so no live app, DB, or network is needed.
"""

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
    def __init__(self, body: bytes):
        self._body = body

    async def read(self, n: int = -1) -> bytes:
        return self._body if n < 0 else self._body[:n]


class FakeResponse:
    def __init__(self, status=200, body=SECRET_BODY, content_type='text/csv'):
        self.status = status
        self.headers = {'Content-Type': content_type}
        self.content = FakeContent(body)


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
        assert resp.media_type == 'text/csv'
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
    async def test_oversize_body_is_502(self):
        big = b'x' * (trc_docs._MAX_BYTES + 1)
        with pytest.raises(HTTPException) as exc:
            await _call(FakeSession(FakeResponse(body=big)))
        assert exc.value.status_code == 502

    @pytest.mark.asyncio
    async def test_body_at_cap_is_served(self):
        body = b'x' * trc_docs._MAX_BYTES
        resp = await _call(FakeSession(FakeResponse(body=body)))
        assert len(resp.body) == trc_docs._MAX_BYTES


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
