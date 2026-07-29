"""Tests that deleting a user notifies RAGnarok to purge every one of their
conversations (path 4) -- UsersTable.delete_user_by_id in models/users.py.

delete_user_by_id imports its collaborators (Chats, Groups, and the RAGnarok
notifier) locally inside the function body, so tests patch the attributes on
the *origin* modules (open_webui.models.chats.Chats, etc.) rather than on
open_webui.models.users -- the local `from X import Y` re-resolves X.Y at
call time, so patching X.Y beforehand is what actually takes effect.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from open_webui.models.users import Users


class _FakeSessionContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _fake_db_session():
    session = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    return session


class TestDeleteUserById:
    @pytest.mark.asyncio
    async def test_notifies_forget_user_after_successful_deletion(self):
        session = _fake_db_session()

        with (
            patch('open_webui.models.groups.Groups.remove_user_from_all_groups', new=AsyncMock()),
            patch('open_webui.models.chats.Chats.delete_chats_by_user_id', new=AsyncMock(return_value=True)),
            patch('open_webui.utils.ragnarok.notify_user_chats_deleted', new=AsyncMock()) as mock_notify,
            patch(
                'open_webui.models.users.get_async_db_context',
                return_value=_FakeSessionContext(session),
            ),
        ):
            result = await Users.delete_user_by_id('user-1')

        assert result is True
        mock_notify.assert_awaited_once_with('user-1')

    @pytest.mark.asyncio
    async def test_does_not_notify_when_chat_deletion_fails(self):
        session = _fake_db_session()

        with (
            patch('open_webui.models.groups.Groups.remove_user_from_all_groups', new=AsyncMock()),
            patch('open_webui.models.chats.Chats.delete_chats_by_user_id', new=AsyncMock(return_value=False)),
            patch('open_webui.utils.ragnarok.notify_user_chats_deleted', new=AsyncMock()) as mock_notify,
            patch(
                'open_webui.models.users.get_async_db_context',
                return_value=_FakeSessionContext(session),
            ),
        ):
            result = await Users.delete_user_by_id('user-1')

        assert result is False
        mock_notify.assert_not_awaited()
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_survives_ragnarok_failure_and_still_reports_success(self):
        """The real (unmocked) notify function must not turn a RAGnarok outage
        into a failed user deletion."""
        session = _fake_db_session()

        from open_webui.utils import ragnarok as ragnarok_module

        with (
            patch('open_webui.models.groups.Groups.remove_user_from_all_groups', new=AsyncMock()),
            patch('open_webui.models.chats.Chats.delete_chats_by_user_id', new=AsyncMock(return_value=True)),
            patch(
                'open_webui.models.users.get_async_db_context',
                return_value=_FakeSessionContext(session),
            ),
            patch.object(ragnarok_module, 'RAGNAROK_BASE_URL', 'http://ragnarok.internal:8000'),
            patch.object(ragnarok_module, 'RAGNAROK_SERVICE_KEY', 'test-key'),
            patch.object(ragnarok_module, 'get_session', new=AsyncMock(side_effect=ConnectionError('down'))),
        ):
            result = await Users.delete_user_by_id('user-1')

        assert result is True
