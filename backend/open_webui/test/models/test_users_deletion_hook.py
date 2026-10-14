"""Tests that deleting a user notifies RAGnarok to purge every one of their
conversations (path 4) -- UsersTable.delete_user_by_id in models/users.py.

delete_user_by_id imports its collaborators (Chats, Groups, and the RAGnarok
notifier) locally inside the function body, so tests patch the attributes on
the *origin* modules (open_webui.models.chats.Chats, etc.) rather than on
open_webui.models.users -- the local `from X import Y` re-resolves X.Y at
call time, so patching X.Y beforehand is what actually takes effect.
"""

from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from open_webui.models.users import Users


class _FakeSessionContext:
    def __init__(self, session, call_order=None):
        self._session = session
        self._call_order = call_order

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        if self._call_order is not None:
            self._call_order.append('session_released')
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
    async def test_notifies_after_the_db_session_is_released(self):
        """The notification is a remote HTTP call. Making it inside the
        `async with get_async_db_context(...)` block holds a checked-out DB
        session for the length of that call, which under a slow RAGnarok is
        how a pool gets exhausted. Everything is committed by then, so there
        is nothing to gain by staying inside."""
        call_order = []
        session = _fake_db_session()

        async def _notify(user_id):
            call_order.append('notify')

        with (
            patch('open_webui.models.groups.Groups.remove_user_from_all_groups', new=AsyncMock()),
            patch('open_webui.models.chats.Chats.delete_chats_by_user_id', new=AsyncMock(return_value=True)),
            patch('open_webui.utils.ragnarok.notify_user_chats_deleted', new=_notify),
            patch(
                'open_webui.models.users.get_async_db_context',
                return_value=_FakeSessionContext(session, call_order),
            ),
        ):
            result = await Users.delete_user_by_id('user-1')

        assert result is True
        assert call_order == ['session_released', 'notify']

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


class TestDeleteUserPurgesFeedback:
    """Deleting a user removes every chat they own. Each rating of those chats -- the user's
    own AND anyone else's (a reader with access can rate a shared chat) -- holds a full,
    unmasked snapshot of one of them, so both are purged: by chat id and by rater."""

    @staticmethod
    def _patches(session, *, delete_result=True, chat_ids=('chat-a', 'chat-b'), purge_by_chat=None, purge_by_user=None):
        return (
            patch('open_webui.models.groups.Groups.remove_user_from_all_groups', new=AsyncMock()),
            patch('open_webui.models.chats.Chats.get_chat_ids_by_user_id', new=AsyncMock(return_value=list(chat_ids))),
            patch('open_webui.models.chats.Chats.delete_chats_by_user_id', new=AsyncMock(return_value=delete_result)),
            patch('open_webui.utils.ragnarok.notify_user_chats_deleted', new=AsyncMock()),
            patch(
                'open_webui.models.feedbacks.Feedbacks.purge_feedbacks_by_chat_ids',
                new=purge_by_chat or AsyncMock(),
            ),
            patch(
                'open_webui.models.feedbacks.Feedbacks.purge_feedbacks_by_user_id',
                new=purge_by_user or AsyncMock(),
            ),
            patch(
                'open_webui.models.users.get_async_db_context',
                return_value=_FakeSessionContext(session),
            ),
        )

    @pytest.mark.asyncio
    async def test_purges_by_the_deleted_chat_ids_and_by_the_user(self):
        by_chat, by_user = AsyncMock(), AsyncMock()

        with ExitStack() as stack:
            for p in self._patches(_fake_db_session(), purge_by_chat=by_chat, purge_by_user=by_user):
                stack.enter_context(p)
            result = await Users.delete_user_by_id('user-1')

        assert result is True
        assert by_chat.await_args.args == (['chat-a', 'chat-b'],)
        assert by_user.await_args.args == ('user-1',)

    @pytest.mark.asyncio
    async def test_purges_nothing_when_chat_deletion_fails(self):
        by_chat, by_user = AsyncMock(), AsyncMock()

        with ExitStack() as stack:
            for p in self._patches(
                _fake_db_session(), delete_result=False, purge_by_chat=by_chat, purge_by_user=by_user
            ):
                stack.enter_context(p)
            result = await Users.delete_user_by_id('user-1')

        assert result is False
        by_chat.assert_not_awaited()
        by_user.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ids_are_collected_before_the_chats_are_deleted(self):
        call_order = []

        async def _list(*args, **kwargs):
            call_order.append('list')
            return ['chat-a']

        async def _delete(*args, **kwargs):
            call_order.append('delete')
            return True

        with (
            patch('open_webui.models.groups.Groups.remove_user_from_all_groups', new=AsyncMock()),
            patch('open_webui.models.chats.Chats.get_chat_ids_by_user_id', new=_list),
            patch('open_webui.models.chats.Chats.delete_chats_by_user_id', new=_delete),
            patch('open_webui.utils.ragnarok.notify_user_chats_deleted', new=AsyncMock()),
            patch('open_webui.models.feedbacks.Feedbacks.purge_feedbacks_by_chat_ids', new=AsyncMock()),
            patch('open_webui.models.feedbacks.Feedbacks.purge_feedbacks_by_user_id', new=AsyncMock()),
            patch(
                'open_webui.models.users.get_async_db_context',
                return_value=_FakeSessionContext(_fake_db_session()),
            ),
        ):
            await Users.delete_user_by_id('user-1')

        assert call_order == ['list', 'delete']

    @pytest.mark.asyncio
    async def test_purges_run_after_the_session_is_released_and_before_the_notification(self):
        call_order = []
        session = _fake_db_session()

        async def _purge_chats(chat_ids, *args, **kwargs):
            call_order.append('purge_chats')
            return 0

        async def _purge_user(user_id, *args, **kwargs):
            call_order.append('purge_user')
            return 0

        async def _notify(user_id):
            call_order.append('notify')

        with (
            patch('open_webui.models.groups.Groups.remove_user_from_all_groups', new=AsyncMock()),
            patch('open_webui.models.chats.Chats.get_chat_ids_by_user_id', new=AsyncMock(return_value=['chat-a'])),
            patch('open_webui.models.chats.Chats.delete_chats_by_user_id', new=AsyncMock(return_value=True)),
            patch('open_webui.utils.ragnarok.notify_user_chats_deleted', new=_notify),
            patch('open_webui.models.feedbacks.Feedbacks.purge_feedbacks_by_chat_ids', new=_purge_chats),
            patch('open_webui.models.feedbacks.Feedbacks.purge_feedbacks_by_user_id', new=_purge_user),
            patch(
                'open_webui.models.users.get_async_db_context',
                return_value=_FakeSessionContext(session, call_order),
            ),
        ):
            await Users.delete_user_by_id('user-1')

        assert call_order == ['session_released', 'purge_chats', 'purge_user', 'notify']
