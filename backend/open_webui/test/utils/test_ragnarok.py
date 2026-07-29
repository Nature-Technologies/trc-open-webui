"""Tests for the RAGnarok chat-deletion notification client.

These tests exercise open_webui.utils.ragnarok in isolation: no real network
call is ever made, aiohttp is faked at the session boundary. The behaviours
under test are the ones the deletion call sites depend on:

  - unset config => no HTTP call is attempted at all.
  - configured => the right endpoint, headers, and JSON body are sent.
  - any failure (timeout, connection error, non-2xx response) is swallowed:
    the coroutine returns normally and never raises.
"""

import asyncio
import logging
import time
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from open_webui.utils import ragnarok


class _FakeResponse:
    def __init__(self, status: int = 200):
        self.status = status


class _NeverAnsweringPostContextManager:
    """A RAGnarok that accepts the connection and then never replies.

    The per-call aiohttp ClientTimeout cannot save the caller here, because
    nothing enforces it once aiohttp is faked out -- which is the point: the
    batch budget has to be what bounds the loop.
    """

    async def __aenter__(self):
        await asyncio.sleep(3600)

    async def __aexit__(self, exc_type, exc, tb):
        return False


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


class TestRequestTimeout:
    """The per-call timeout has no safe fallback, so it is asserted explicitly.

    Without the explicit `timeout=` kwarg each request inherits the shared
    session's default, which is aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT)
    -- and env.py leaves AIOHTTP_CLIENT_TIMEOUT as None when the variable is
    unset, meaning UNLIMITED. A hung RAGnarok would then hang chat deletion
    forever while every other test in this file stayed green, because they
    assert the URL, body and headers and nothing about how long a call may
    take. The batch budget bounds a folder's whole loop; this bounds the single
    call that the other three deletion paths make.
    """

    @pytest.mark.asyncio
    async def test_notify_chat_deleted_sends_an_explicit_total_timeout(self):
        session = _fake_session(_FakePostContextManager(response=_FakeResponse(200)))

        with patch.object(ragnarok, 'get_session', new=AsyncMock(return_value=session)):
            await ragnarok.notify_chat_deleted('user-1', 'chat-1')

        timeout = session.post.call_args.kwargs['timeout']
        assert timeout.total == ragnarok._REQUEST_TIMEOUT_SECONDS
        assert timeout.total is not None

    @pytest.mark.asyncio
    async def test_notify_user_chats_deleted_sends_an_explicit_total_timeout(self):
        session = _fake_session(_FakePostContextManager(response=_FakeResponse(200)))

        with patch.object(ragnarok, 'get_session', new=AsyncMock(return_value=session)):
            await ragnarok.notify_user_chats_deleted('user-1')

        timeout = session.post.call_args.kwargs['timeout']
        assert timeout.total == ragnarok._REQUEST_TIMEOUT_SECONDS
        assert timeout.total is not None

    def test_the_configured_timeout_is_actually_bounded(self):
        """Guards the constant itself: `_REQUEST_TIMEOUT_SECONDS = None` would
        satisfy both assertions above by passing an unlimited ClientTimeout."""
        assert isinstance(ragnarok._REQUEST_TIMEOUT_SECONDS, (int, float))
        assert 0 < ragnarok._REQUEST_TIMEOUT_SECONDS <= 30


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

    @pytest.mark.asyncio
    async def test_a_credential_bearing_exception_message_is_not_logged_verbatim(self, monkeypatch, caplog):
        """A malformed RAGNAROK_BASE_URL doesn't just fail to connect -- aiohttp's
        own InvalidUrlClientError echoes the exact URL it failed to parse,
        credentials included, as str(exception). Reproduced live against a real
        aiohttp session with RAGNAROK_BASE_URL = 'http://svc:sup3r-s3cret@[bad':
        the password appeared in cleartext at WARNING before this fix."""
        monkeypatch.setattr(ragnarok, 'RAGNAROK_BASE_URL', 'http://svc:sup3r-s3cret@[bad')
        exc = aiohttp.InvalidUrlClientError('http://svc:sup3r-s3cret@[bad/api/redaction/forget')
        session = _fake_session(_FakePostContextManager(exception=exc))

        with patch.object(ragnarok, 'get_session', new=AsyncMock(return_value=session)):
            with caplog.at_level(logging.WARNING, logger='open_webui.utils.ragnarok'):
                await ragnarok.notify_chat_deleted('user1', 'chat1')

        logged = ' '.join(record.getMessage() for record in caplog.records)
        assert 'sup3r-s3cret' not in logged
        assert 'svc' not in logged
        assert '@' not in logged
        # The warning still fired -- this is about redaction, not suppression.
        assert any(record.levelno == logging.WARNING for record in caplog.records)


class TestBatchBudget:
    """notify_chats_deleted must cost a FIXED amount of time, not one
    per-call timeout per chat. A folder subtree with hundreds of chats
    against an unresponsive RAGnarok is the case that matters."""

    @pytest.mark.asyncio
    async def test_batch_stops_at_the_overall_budget_however_many_chats(self, monkeypatch):
        monkeypatch.setattr(ragnarok, '_BATCH_BUDGET_SECONDS', 0.1)
        session = _fake_session(_NeverAnsweringPostContextManager())

        with patch.object(ragnarok, 'get_session', new=AsyncMock(return_value=session)):
            started = time.monotonic()
            await ragnarok.notify_chats_deleted('user-1', [f'chat-{i}' for i in range(300)])
            elapsed = time.monotonic() - started

        # Bounded by the ONE budget. Per-call bounding would be 300 * 5s here.
        assert elapsed < 2
        # And it really did give up rather than silently notifying nothing.
        assert session.post.call_count == 1

    @pytest.mark.asyncio
    async def test_exhausting_the_budget_does_not_raise(self, monkeypatch):
        monkeypatch.setattr(ragnarok, '_BATCH_BUDGET_SECONDS', 0.05)
        session = _fake_session(_NeverAnsweringPostContextManager())

        with patch.object(ragnarok, 'get_session', new=AsyncMock(return_value=session)):
            # Must complete normally: a deletion is never failed by this hook.
            await ragnarok.notify_chats_deleted('user-1', ['chat-a', 'chat-b'])

    @pytest.mark.asyncio
    async def test_notifies_every_chat_when_ragnarok_is_responsive(self):
        session = _fake_session(_FakePostContextManager(response=_FakeResponse(200)))

        with patch.object(ragnarok, 'get_session', new=AsyncMock(return_value=session)):
            await ragnarok.notify_chats_deleted('user-42', ['chat-a', 'chat-b', 'chat-c'])

        posted = [call.kwargs['json'] for call in session.post.call_args_list]
        assert posted == [
            {'conversation_key': 'user-42:chat-a'},
            {'conversation_key': 'user-42:chat-b'},
            {'conversation_key': 'user-42:chat-c'},
        ]

    @pytest.mark.asyncio
    async def test_empty_batch_makes_no_call(self):
        with patch.object(ragnarok, 'get_session', new=AsyncMock()) as mock_get_session:
            await ragnarok.notify_chats_deleted('user-1', [])

        mock_get_session.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_external_cancellation_is_not_swallowed(self, monkeypatch):
        """Distinct from the budget expiring: a caller cancelling this task --
        graceful shutdown, client disconnect -- must still stop it. asyncio's
        timeout context re-raises CancelledError rather than converting it, and
        nothing here may catch it, or shutdown hangs on a best-effort assist."""
        monkeypatch.setattr(ragnarok, '_BATCH_BUDGET_SECONDS', 3600)
        session = _fake_session(_NeverAnsweringPostContextManager())

        with patch.object(ragnarok, 'get_session', new=AsyncMock(return_value=session)):
            task = asyncio.ensure_future(ragnarok.notify_chats_deleted('user-1', ['chat-a']))
            await asyncio.sleep(0)  # let it reach the first await
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


class TestUnexpectedBatchFailureIsSwallowed:
    """notify_chats_deleted used to catch only TimeoutError. Anything else
    escaping it propagates into folders.py's `except Exception`, which
    returns HTTP 400 -- but by the time this hook runs, the folder/chat rows
    are already committed and every access grant already revoked, so that
    response would tell the client a successful deletion failed. Nothing
    plausible raises here today (_notify already swallows a single call's
    own failures); this guards the fail-safe shape regardless."""

    @pytest.mark.asyncio
    async def test_a_non_timeout_exception_from_the_batch_loop_does_not_raise(self, monkeypatch):
        async def _boom(user_id, chat_id):
            raise RuntimeError('unexpected failure inside the per-call helper')

        monkeypatch.setattr(ragnarok, 'notify_chat_deleted', _boom)

        # Must complete without raising.
        await ragnarok.notify_chats_deleted('user-1', ['chat-a', 'chat-b'])

    @pytest.mark.asyncio
    async def test_the_unexpected_failure_is_logged_at_warning(self, monkeypatch, caplog):
        async def _boom(user_id, chat_id):
            raise RuntimeError('unexpected failure inside the per-call helper')

        monkeypatch.setattr(ragnarok, 'notify_chat_deleted', _boom)

        with caplog.at_level(logging.WARNING, logger='open_webui.utils.ragnarok'):
            await ragnarok.notify_chats_deleted('user-1', ['chat-a'])

        assert any(record.levelno == logging.WARNING for record in caplog.records)

    @pytest.mark.asyncio
    async def test_cancellation_is_still_not_swallowed_here_either(self, monkeypatch):
        """The broadened except must stay narrower than BaseException, or a
        real cancellation (shutdown, client disconnect) would be absorbed by
        a best-effort assist instead of propagating."""

        async def _boom(user_id, chat_id):
            raise asyncio.CancelledError()

        monkeypatch.setattr(ragnarok, 'notify_chat_deleted', _boom)

        with pytest.raises(asyncio.CancelledError):
            await ragnarok.notify_chats_deleted('user-1', ['chat-a'])


class TestStartupLogging:
    def test_logs_enabled_when_configured(self, caplog):
        with caplog.at_level(logging.INFO, logger='open_webui.utils.ragnarok'):
            ragnarok.log_startup_status()

        assert any('enabled' in record.message for record in caplog.records)

    def test_credentials_in_the_base_url_are_not_logged(self, caplog, monkeypatch):
        """The startup line is INFO, so it must survive a base URL that
        carries userinfo -- the one shape of RAGNAROK_BASE_URL that turns a
        harmless config echo into a credential leak."""
        monkeypatch.setattr(ragnarok, 'RAGNAROK_BASE_URL', 'https://svc:sup3r-s3cret@ragnarok.internal:8443/base')

        with caplog.at_level(logging.INFO, logger='open_webui.utils.ragnarok'):
            ragnarok.log_startup_status()

        logged = ' '.join(record.getMessage() for record in caplog.records)
        assert 'sup3r-s3cret' not in logged
        assert 'svc' not in logged
        assert '@' not in logged
        # Still useful: the operator can see which RAGnarok it points at.
        assert 'https://ragnarok.internal:8443/base' in logged

    def test_credentials_in_the_base_url_are_flagged_as_inert_not_just_redacted(self, caplog, monkeypatch):
        """Redacting the credentials from the log (above) is necessary but not
        sufficient: aiohttp refuses to combine URL-embedded credentials with
        the Authorization header this client always sends, so this shape of
        RAGNAROK_BASE_URL doesn't just risk a log leak -- it makes EVERY
        notification fail silently, forever. That must be visible at
        startup, at WARNING, not folded into the routine 'enabled' INFO line."""
        monkeypatch.setattr(ragnarok, 'RAGNAROK_BASE_URL', 'https://svc:sup3r-s3cret@ragnarok.internal:8443/base')

        with caplog.at_level(logging.INFO, logger='open_webui.utils.ragnarok'):
            ragnarok.log_startup_status()

        assert any(record.levelno == logging.WARNING for record in caplog.records)
        logged = ' '.join(record.getMessage() for record in caplog.records)
        assert 'enabled' not in logged

    def test_a_username_only_base_url_is_also_flagged(self, caplog, monkeypatch):
        """Userinfo doesn't require a password -- scheme://user@host is legal
        too, and triggers the same aiohttp conflict."""
        monkeypatch.setattr(ragnarok, 'RAGNAROK_BASE_URL', 'https://svc@ragnarok.internal:8443/base')

        with caplog.at_level(logging.WARNING, logger='open_webui.utils.ragnarok'):
            ragnarok.log_startup_status()

        assert any(record.levelno == logging.WARNING for record in caplog.records)

    def test_an_unparseable_base_url_is_not_echoed_verbatim(self, caplog, monkeypatch):
        monkeypatch.setattr(ragnarok, 'RAGNAROK_BASE_URL', 'not a url with a s3cret in it')

        with caplog.at_level(logging.INFO, logger='open_webui.utils.ragnarok'):
            ragnarok.log_startup_status()

        logged = ' '.join(record.getMessage() for record in caplog.records)
        assert 's3cret' not in logged
        assert '<unparseable>' in logged

    def test_an_ordinary_base_url_is_logged_intact(self, caplog):
        with caplog.at_level(logging.INFO, logger='open_webui.utils.ragnarok'):
            ragnarok.log_startup_status()

        logged = ' '.join(record.getMessage() for record in caplog.records)
        assert 'http://ragnarok.internal:8000' in logged

    def test_logs_disabled_when_unconfigured(self, caplog, monkeypatch):
        monkeypatch.setattr(ragnarok, 'RAGNAROK_BASE_URL', '')
        monkeypatch.setattr(ragnarok, 'RAGNAROK_SERVICE_KEY', '')

        with caplog.at_level(logging.INFO, logger='open_webui.utils.ragnarok'):
            ragnarok.log_startup_status()

        assert any('disabled' in record.message for record in caplog.records)


class TestRedactUrlCredentials:
    """Unit tests for the helper _notify uses to sanitize exception text
    before logging it -- see TestFailuresAreSwallowed for the integrated
    version against a real aiohttp exception."""

    def test_strips_user_and_password(self):
        text = 'http://svc:sup3r-s3cret@ragnarok.internal:8443/api/redaction/forget'
        redacted = ragnarok._redact_url_credentials(text)
        assert 'sup3r-s3cret' not in redacted
        assert 'svc' not in redacted
        assert 'ragnarok.internal:8443/api/redaction/forget' in redacted

    def test_strips_username_only(self):
        text = 'http://svc@ragnarok.internal/path'
        redacted = ragnarok._redact_url_credentials(text)
        assert 'svc' not in redacted
        assert 'ragnarok.internal/path' in redacted

    def test_leaves_credential_free_text_untouched(self):
        text = 'Cannot combine AUTHORIZATION header with AUTH argument or credentials encoded in URL'
        assert ragnarok._redact_url_credentials(text) == text
