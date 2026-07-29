"""Tests for the RAGnarok chat-deletion notification client.

These tests exercise open_webui.utils.ragnarok in isolation: no real network
call is ever made, aiohttp is faked at the session boundary. The behaviours
under test are the ones the deletion call sites depend on:

  - unset config => no HTTP call is attempted at all.
  - configured => the right endpoint, headers, and JSON body are sent.
  - any failure (timeout, connection error, non-2xx response) is swallowed:
    the coroutine returns normally and never raises.
"""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from open_webui.utils import ragnarok


class _FakeResponse:
    def __init__(self, status: int = 200):
        self.status = status


class _FakePostContextManager:
    """Stands in for the object aiohttp's ClientSession.post(...) returns.

    Used as `async with session.post(...) as response:`, matching how
    open_webui.utils.ragnarok._notify actually calls it.
    """

    def __init__(self, response=None, exception=None):
        self._response = response
        self._exception = exception

    async def __aenter__(self):
        if self._exception is not None:
            raise self._exception
        return self._response

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _fake_session(post_context_manager):
    session = MagicMock()
    session.post = MagicMock(return_value=post_context_manager)
    return session


@pytest.fixture(autouse=True)
def _configured(monkeypatch):
    """Most tests want RAGnarok configured; unconfigured tests override this."""
    monkeypatch.setattr(ragnarok, 'RAGNAROK_BASE_URL', 'http://ragnarok.internal:8000')
    monkeypatch.setattr(ragnarok, 'RAGNAROK_SERVICE_KEY', 'test-service-key')


class TestNotConfigured:
    @pytest.mark.asyncio
    async def test_notify_chat_deleted_makes_no_http_call_when_unset(self, monkeypatch):
        monkeypatch.setattr(ragnarok, 'RAGNAROK_BASE_URL', '')
        monkeypatch.setattr(ragnarok, 'RAGNAROK_SERVICE_KEY', '')

        with patch.object(ragnarok, 'get_session', new=AsyncMock()) as mock_get_session:
            await ragnarok.notify_chat_deleted('user1', 'chat1')

        mock_get_session.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_notify_user_chats_deleted_makes_no_http_call_when_key_missing(self, monkeypatch):
        # Base URL set but service key missing -- still must not fire.
        monkeypatch.setattr(ragnarok, 'RAGNAROK_BASE_URL', 'http://ragnarok.internal:8000')
        monkeypatch.setattr(ragnarok, 'RAGNAROK_SERVICE_KEY', '')

        with patch.object(ragnarok, 'get_session', new=AsyncMock()) as mock_get_session:
            await ragnarok.notify_user_chats_deleted('user1')

        mock_get_session.assert_not_awaited()


class TestSuccessfulNotification:
    @pytest.mark.asyncio
    async def test_notify_chat_deleted_posts_forget_with_conversation_key(self):
        session = _fake_session(_FakePostContextManager(response=_FakeResponse(200)))

        with patch.object(ragnarok, 'get_session', new=AsyncMock(return_value=session)):
            await ragnarok.notify_chat_deleted('user-42', 'chat-99')

        session.post.assert_called_once()
        args, kwargs = session.post.call_args
        assert args[0] == 'http://ragnarok.internal:8000/api/redaction/forget'
        assert kwargs['json'] == {'conversation_key': 'user-42:chat-99'}
        assert kwargs['headers']['Authorization'] == 'Bearer test-service-key'

    @pytest.mark.asyncio
    async def test_notify_user_chats_deleted_posts_forget_user_with_user_id(self):
        session = _fake_session(_FakePostContextManager(response=_FakeResponse(200)))

        with patch.object(ragnarok, 'get_session', new=AsyncMock(return_value=session)):
            await ragnarok.notify_user_chats_deleted('user-42')

        session.post.assert_called_once()
        args, kwargs = session.post.call_args
        assert args[0] == 'http://ragnarok.internal:8000/api/redaction/forget-user'
        assert kwargs['json'] == {'user_id': 'user-42'}
        assert kwargs['headers']['Authorization'] == 'Bearer test-service-key'

    @pytest.mark.asyncio
    async def test_base_url_trailing_slash_is_normalized(self, monkeypatch):
        monkeypatch.setattr(ragnarok, 'RAGNAROK_BASE_URL', 'http://ragnarok.internal:8000/')
        session = _fake_session(_FakePostContextManager(response=_FakeResponse(200)))

        with patch.object(ragnarok, 'get_session', new=AsyncMock(return_value=session)):
            await ragnarok.notify_chat_deleted('user1', 'chat1')

        args, _ = session.post.call_args
        assert args[0] == 'http://ragnarok.internal:8000/api/redaction/forget'


class TestFailuresAreSwallowed:
    @pytest.mark.asyncio
    async def test_timeout_does_not_raise(self):
        session = _fake_session(_FakePostContextManager(exception=TimeoutError()))

        with patch.object(ragnarok, 'get_session', new=AsyncMock(return_value=session)):
            # Must complete without raising.
            await ragnarok.notify_chat_deleted('user1', 'chat1')

    @pytest.mark.asyncio
    async def test_connection_error_does_not_raise(self):
        session = _fake_session(_FakePostContextManager(exception=aiohttp.ClientConnectionError('unreachable')))

        with patch.object(ragnarok, 'get_session', new=AsyncMock(return_value=session)):
            await ragnarok.notify_user_chats_deleted('user1')

    @pytest.mark.asyncio
    async def test_500_response_does_not_raise(self):
        session = _fake_session(_FakePostContextManager(response=_FakeResponse(500)))

        with patch.object(ragnarok, 'get_session', new=AsyncMock(return_value=session)):
            await ragnarok.notify_chat_deleted('user1', 'chat1')

    @pytest.mark.asyncio
    async def test_get_session_itself_failing_does_not_raise(self):
        with patch.object(ragnarok, 'get_session', new=AsyncMock(side_effect=RuntimeError('pool exhausted'))):
            await ragnarok.notify_chat_deleted('user1', 'chat1')

    @pytest.mark.asyncio
    async def test_timeout_is_logged_at_warning(self, caplog):
        session = _fake_session(_FakePostContextManager(exception=TimeoutError()))

        with patch.object(ragnarok, 'get_session', new=AsyncMock(return_value=session)):
            with caplog.at_level(logging.WARNING, logger='open_webui.utils.ragnarok'):
                await ragnarok.notify_chat_deleted('user1', 'chat1')

        assert any(record.levelno == logging.WARNING for record in caplog.records)


class TestStartupLogging:
    def test_logs_enabled_when_configured(self, caplog):
        with caplog.at_level(logging.INFO, logger='open_webui.utils.ragnarok'):
            ragnarok.log_startup_status()

        assert any('enabled' in record.message for record in caplog.records)

    def test_logs_disabled_when_unconfigured(self, caplog, monkeypatch):
        monkeypatch.setattr(ragnarok, 'RAGNAROK_BASE_URL', '')
        monkeypatch.setattr(ragnarok, 'RAGNAROK_SERVICE_KEY', '')

        with caplog.at_level(logging.INFO, logger='open_webui.utils.ragnarok'):
            ragnarok.log_startup_status()

        assert any('disabled' in record.message for record in caplog.records)
