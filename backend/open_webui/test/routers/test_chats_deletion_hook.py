"""Tests that chat-deletion routes notify RAGnarok correctly.

Covers the two call sites for path 1 (single-chat DELETE /{id}, admin and
owner branches) and path 2 (DELETE /, delete-all-of-my-chats) described in
the deletion-hook task. Router functions are invoked directly as plain
coroutines (FastAPI's @router.delete decorator returns the undecorated
function), with their module-level collaborators patched, so no live app,
DB, or network is needed.
"""

from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from open_webui.routers import chats as chats_router


def _request():
    request = MagicMock()
    request.app.state.redis = None
    return request


def _chat(id: str, user_id: str, tags=None):
    chat = MagicMock()
    chat.id = id
    chat.user_id = user_id
    chat.meta = {'tags': tags or []}
    return chat


class TestDeleteChatByIdAdminBranch:
    """DELETE /{id}, admin role -- the branch around line ~1456 in chats.py."""

    @pytest.mark.asyncio
    async def test_admin_delete_notifies_with_chat_owner_id_not_admin_id(self):
        admin = SimpleNamespace(id='admin-1', role='admin')
        chat = _chat(id='chat-1', user_id='owner-1')

        with (
            patch.object(chats_router, 'stop_item_tasks', new=AsyncMock()),
            patch.object(chats_router.Chats, 'get_chat_by_id', new=AsyncMock(return_value=chat)),
            patch.object(chats_router.Chats, 'delete_orphan_tags_for_user', new=AsyncMock()),
            patch.object(chats_router.Chats, 'delete_chat_by_id', new=AsyncMock(return_value=True)),
            patch.object(chats_router, 'publish_event', new=AsyncMock()),
            patch.object(chats_router, 'notify_chat_deleted', new=AsyncMock()) as mock_notify,
        ):
            result = await chats_router.delete_chat_by_id(request=_request(), id='chat-1', user=admin, db=MagicMock())

        assert result is True
        # The deleting admin is 'admin-1'; the conversation key must use the
        # chat's real owner, 'owner-1', or purging targets the wrong mappings.
        mock_notify.assert_awaited_once_with('owner-1', 'chat-1')

    @pytest.mark.asyncio
    async def test_admin_delete_does_not_notify_when_deletion_fails(self):
        admin = SimpleNamespace(id='admin-1', role='admin')
        chat = _chat(id='chat-1', user_id='owner-1')

        with (
            patch.object(chats_router, 'stop_item_tasks', new=AsyncMock()),
            patch.object(chats_router.Chats, 'get_chat_by_id', new=AsyncMock(return_value=chat)),
            patch.object(chats_router.Chats, 'delete_orphan_tags_for_user', new=AsyncMock()),
            patch.object(chats_router.Chats, 'delete_chat_by_id', new=AsyncMock(return_value=False)),
            patch.object(chats_router, 'publish_event', new=AsyncMock()),
            patch.object(chats_router, 'notify_chat_deleted', new=AsyncMock()) as mock_notify,
        ):
            result = await chats_router.delete_chat_by_id(request=_request(), id='chat-1', user=admin, db=MagicMock())

        assert result is False
        mock_notify.assert_not_awaited()


class TestDeleteChatByIdOwnerBranch:
    """DELETE /{id}, non-admin owner -- the branch around line ~1489 in chats.py."""

    @pytest.mark.asyncio
    async def test_owner_delete_notifies_with_own_id(self):
        user = SimpleNamespace(id='owner-1', role='user')
        chat = _chat(id='chat-1', user_id='owner-1')

        with (
            patch.object(chats_router, 'stop_item_tasks', new=AsyncMock()),
            patch.object(chats_router, 'has_permission', new=AsyncMock(return_value=True)),
            patch.object(chats_router.Config, 'get', new=AsyncMock(return_value={})),
            patch.object(chats_router.Chats, 'get_chat_by_id_and_user_id', new=AsyncMock(return_value=chat)),
            patch.object(chats_router.Chats, 'delete_orphan_tags_for_user', new=AsyncMock()),
            patch.object(chats_router.Chats, 'delete_chat_by_id_and_user_id', new=AsyncMock(return_value=True)),
            patch.object(chats_router, 'publish_event', new=AsyncMock()),
            patch.object(chats_router, 'notify_chat_deleted', new=AsyncMock()) as mock_notify,
        ):
            result = await chats_router.delete_chat_by_id(request=_request(), id='chat-1', user=user, db=MagicMock())

        assert result is True
        mock_notify.assert_awaited_once_with('owner-1', 'chat-1')

    @pytest.mark.asyncio
    async def test_owner_delete_does_not_notify_when_deletion_fails(self):
        user = SimpleNamespace(id='owner-1', role='user')
        chat = _chat(id='chat-1', user_id='owner-1')

        with (
            patch.object(chats_router, 'stop_item_tasks', new=AsyncMock()),
            patch.object(chats_router, 'has_permission', new=AsyncMock(return_value=True)),
            patch.object(chats_router.Config, 'get', new=AsyncMock(return_value={})),
            patch.object(chats_router.Chats, 'get_chat_by_id_and_user_id', new=AsyncMock(return_value=chat)),
            patch.object(chats_router.Chats, 'delete_orphan_tags_for_user', new=AsyncMock()),
            patch.object(chats_router.Chats, 'delete_chat_by_id_and_user_id', new=AsyncMock(return_value=False)),
            patch.object(chats_router, 'publish_event', new=AsyncMock()),
            patch.object(chats_router, 'notify_chat_deleted', new=AsyncMock()) as mock_notify,
        ):
            result = await chats_router.delete_chat_by_id(request=_request(), id='chat-1', user=user, db=MagicMock())

        assert result is False
        mock_notify.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_owner_delete_survives_ragnarok_timeout(self):
        """The real (unmocked) notify function must not turn a slow/unreachable
        RAGnarok into a failed chat deletion. Configure it, then make the
        underlying session raise, and confirm the route still returns True.
        """
        user = SimpleNamespace(id='owner-1', role='user')
        chat = _chat(id='chat-1', user_id='owner-1')

        from open_webui.utils import ragnarok as ragnarok_module

        with (
            patch.object(chats_router, 'stop_item_tasks', new=AsyncMock()),
            patch.object(chats_router, 'has_permission', new=AsyncMock(return_value=True)),
            patch.object(chats_router.Config, 'get', new=AsyncMock(return_value={})),
            patch.object(chats_router.Chats, 'get_chat_by_id_and_user_id', new=AsyncMock(return_value=chat)),
            patch.object(chats_router.Chats, 'delete_orphan_tags_for_user', new=AsyncMock()),
            patch.object(chats_router.Chats, 'delete_chat_by_id_and_user_id', new=AsyncMock(return_value=True)),
            patch.object(chats_router, 'publish_event', new=AsyncMock()),
            patch.object(ragnarok_module, 'RAGNAROK_BASE_URL', 'http://ragnarok.internal:8000'),
            patch.object(ragnarok_module, 'RAGNAROK_SERVICE_KEY', 'test-key'),
            patch.object(ragnarok_module, 'get_session', new=AsyncMock(side_effect=TimeoutError('slow'))),
        ):
            result = await chats_router.delete_chat_by_id(request=_request(), id='chat-1', user=user, db=MagicMock())

        assert result is True


class TestDeleteAllUserChats:
    """DELETE / -- delete every chat the calling user owns (path 2)."""

    @pytest.mark.asyncio
    async def test_notifies_forget_user_for_calling_user(self):
        user = SimpleNamespace(id='user-1', role='user')

        with (
            patch.object(chats_router, 'has_permission', new=AsyncMock(return_value=True)),
            patch.object(chats_router.Config, 'get', new=AsyncMock(return_value={})),
            patch.object(chats_router.Chats, 'delete_chats_by_user_id', new=AsyncMock(return_value=True)),
            patch.object(chats_router, 'publish_event', new=AsyncMock()),
            patch.object(chats_router, 'notify_user_chats_deleted', new=AsyncMock()) as mock_notify,
        ):
            result = await chats_router.delete_all_user_chats(request=_request(), user=user, db=MagicMock())

        assert result is True
        mock_notify.assert_awaited_once_with('user-1')

    @pytest.mark.asyncio
    async def test_does_not_notify_when_deletion_fails(self):
        user = SimpleNamespace(id='user-1', role='user')

        with (
            patch.object(chats_router, 'has_permission', new=AsyncMock(return_value=True)),
            patch.object(chats_router.Config, 'get', new=AsyncMock(return_value={})),
            patch.object(chats_router.Chats, 'delete_chats_by_user_id', new=AsyncMock(return_value=False)),
            patch.object(chats_router, 'publish_event', new=AsyncMock()),
            patch.object(chats_router, 'notify_user_chats_deleted', new=AsyncMock()) as mock_notify,
        ):
            result = await chats_router.delete_all_user_chats(request=_request(), user=user, db=MagicMock())

        assert result is False
        mock_notify.assert_not_awaited()


class TestFeedbackPurgeOnChatDelete:
    """A feedback row's snapshot is a full, unmasked copy of the chat it rates, so both
    chat-delete routes purge it -- only after the delete succeeds, keyed on the chat."""

    @pytest.mark.asyncio
    async def test_admin_delete_purges_each_deleted_chat_by_id_children_first(self):
        admin = SimpleNamespace(id='admin-1', role='admin')
        chat = _chat(id='chat-1', user_id='owner-1')

        with (
            patch.object(chats_router, 'stop_item_tasks', new=AsyncMock()),
            patch.object(chats_router.Chats, 'get_chat_by_id', new=AsyncMock(return_value=chat)),
            patch.object(chats_router.Chats, 'delete_orphan_tags_for_user', new=AsyncMock()),
            patch.object(
                chats_router.Chats, 'get_internal_chat_ids_by_parent_id', new=AsyncMock(return_value=['child-1'])
            ),
            patch.object(chats_router.Chats, 'delete_chat_by_id_and_user_id', new=AsyncMock(return_value=True)),
            patch.object(chats_router.Chats, 'delete_chat_by_id', new=AsyncMock(return_value=True)),
            patch.object(chats_router, 'publish_event', new=AsyncMock()),
            patch.object(chats_router, 'notify_chat_deleted', new=AsyncMock()),
            patch.object(chats_router.Feedbacks, 'purge_feedbacks_by_chat_ids', new=AsyncMock()) as mock_purge,
        ):
            result = await chats_router.delete_chat_by_id(request=_request(), id='chat-1', user=admin, db=MagicMock())

        assert result is True
        assert [call.args for call in mock_purge.await_args_list] == [(['child-1'],), (['chat-1'],)]

    @pytest.mark.asyncio
    async def test_owner_delete_purges_by_chat_id(self):
        user = SimpleNamespace(id='owner-1', role='user')
        chat = _chat(id='chat-1', user_id='owner-1')

        with (
            patch.object(chats_router, 'stop_item_tasks', new=AsyncMock()),
            patch.object(chats_router, 'has_permission', new=AsyncMock(return_value=True)),
            patch.object(chats_router.Config, 'get', new=AsyncMock(return_value={})),
            patch.object(chats_router.Chats, 'get_chat_by_id_and_user_id', new=AsyncMock(return_value=chat)),
            patch.object(chats_router.Chats, 'delete_orphan_tags_for_user', new=AsyncMock()),
            patch.object(chats_router.Chats, 'get_internal_chat_ids_by_parent_id', new=AsyncMock(return_value=[])),
            patch.object(chats_router.Chats, 'delete_chat_by_id_and_user_id', new=AsyncMock(return_value=True)),
            patch.object(chats_router, 'publish_event', new=AsyncMock()),
            patch.object(chats_router, 'notify_chat_deleted', new=AsyncMock()),
            patch.object(chats_router.Feedbacks, 'purge_feedbacks_by_chat_ids', new=AsyncMock()) as mock_purge,
        ):
            result = await chats_router.delete_chat_by_id(request=_request(), id='chat-1', user=user, db=MagicMock())

        assert result is True
        assert mock_purge.await_args.args == (['chat-1'],)

    @pytest.mark.asyncio
    async def test_failed_delete_purges_nothing(self):
        user = SimpleNamespace(id='owner-1', role='user')
        chat = _chat(id='chat-1', user_id='owner-1')

        with (
            patch.object(chats_router, 'stop_item_tasks', new=AsyncMock()),
            patch.object(chats_router, 'has_permission', new=AsyncMock(return_value=True)),
            patch.object(chats_router.Config, 'get', new=AsyncMock(return_value={})),
            patch.object(chats_router.Chats, 'get_chat_by_id_and_user_id', new=AsyncMock(return_value=chat)),
            patch.object(chats_router.Chats, 'delete_orphan_tags_for_user', new=AsyncMock()),
            patch.object(chats_router.Chats, 'get_internal_chat_ids_by_parent_id', new=AsyncMock(return_value=[])),
            patch.object(chats_router.Chats, 'delete_chat_by_id_and_user_id', new=AsyncMock(return_value=False)),
            patch.object(chats_router, 'publish_event', new=AsyncMock()),
            patch.object(chats_router, 'notify_chat_deleted', new=AsyncMock()),
            patch.object(chats_router.Feedbacks, 'purge_feedbacks_by_chat_ids', new=AsyncMock()) as mock_purge,
        ):
            result = await chats_router.delete_chat_by_id(request=_request(), id='chat-1', user=user, db=MagicMock())

        assert result is False
        mock_purge.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_purge_runs_before_the_ragnarok_notification(self):
        user = SimpleNamespace(id='owner-1', role='user')
        chat = _chat(id='chat-1', user_id='owner-1')
        call_order = []

        async def _purge(*args, **kwargs):
            call_order.append('purge')
            return 1

        async def _notify(*args, **kwargs):
            call_order.append('notify')

        with (
            patch.object(chats_router, 'stop_item_tasks', new=AsyncMock()),
            patch.object(chats_router, 'has_permission', new=AsyncMock(return_value=True)),
            patch.object(chats_router.Config, 'get', new=AsyncMock(return_value={})),
            patch.object(chats_router.Chats, 'get_chat_by_id_and_user_id', new=AsyncMock(return_value=chat)),
            patch.object(chats_router.Chats, 'delete_orphan_tags_for_user', new=AsyncMock()),
            patch.object(chats_router.Chats, 'get_internal_chat_ids_by_parent_id', new=AsyncMock(return_value=[])),
            patch.object(chats_router.Chats, 'delete_chat_by_id_and_user_id', new=AsyncMock(return_value=True)),
            patch.object(chats_router, 'publish_event', new=AsyncMock()),
            patch.object(chats_router, 'notify_chat_deleted', new=_notify),
            patch.object(chats_router.Feedbacks, 'purge_feedbacks_by_chat_ids', new=_purge),
        ):
            await chats_router.delete_chat_by_id(request=_request(), id='chat-1', user=user, db=MagicMock())

        assert call_order == ['purge', 'notify']


class TestFeedbackPurgeSurvivesPartialFailure:
    """Child chats are deleted before the parent. Whatever happens to the parent, each child
    that really was deleted must lose its feedback snapshots; one that was not must keep them."""

    @staticmethod
    def _patches(user_chat, delete_child_and_parent):
        return (
            patch.object(chats_router, 'stop_item_tasks', new=AsyncMock()),
            patch.object(chats_router, 'has_permission', new=AsyncMock(return_value=True)),
            patch.object(chats_router.Config, 'get', new=AsyncMock(return_value={})),
            patch.object(chats_router.Chats, 'get_chat_by_id_and_user_id', new=AsyncMock(return_value=user_chat)),
            patch.object(chats_router.Chats, 'delete_orphan_tags_for_user', new=AsyncMock()),
            patch.object(
                chats_router.Chats,
                'get_internal_chat_ids_by_parent_id',
                new=AsyncMock(return_value=['child-1', 'child-2']),
            ),
            patch.object(
                chats_router.Chats,
                'delete_chat_by_id_and_user_id',
                new=AsyncMock(side_effect=delete_child_and_parent),
            ),
            patch.object(chats_router, 'publish_event', new=AsyncMock()),
            patch.object(chats_router, 'notify_chat_deleted', new=AsyncMock()),
        )

    @pytest.mark.asyncio
    async def test_children_are_purged_when_the_parent_delete_fails(self):
        user = SimpleNamespace(id='owner-1', role='user')
        chat = _chat(id='chat-1', user_id='owner-1')

        with ExitStack() as stack:
            for p in self._patches(chat, lambda chat_id, user_id, db=None: chat_id != 'chat-1'):
                stack.enter_context(p)
            mock_purge = stack.enter_context(
                patch.object(chats_router.Feedbacks, 'purge_feedbacks_by_chat_ids', new=AsyncMock())
            )
            result = await chats_router.delete_chat_by_id(request=_request(), id='chat-1', user=user, db=MagicMock())

        assert result is False
        assert [call.args for call in mock_purge.await_args_list] == [(['child-1'],), (['child-2'],)]

    @pytest.mark.asyncio
    async def test_children_are_purged_when_the_parent_delete_raises(self):
        user = SimpleNamespace(id='owner-1', role='user')
        chat = _chat(id='chat-1', user_id='owner-1')

        def _delete(chat_id, user_id, db=None):
            if chat_id == 'chat-1':
                raise RuntimeError('db down')
            return True

        with ExitStack() as stack:
            for p in self._patches(chat, _delete):
                stack.enter_context(p)
            mock_purge = stack.enter_context(
                patch.object(chats_router.Feedbacks, 'purge_feedbacks_by_chat_ids', new=AsyncMock())
            )
            with pytest.raises(RuntimeError):
                await chats_router.delete_chat_by_id(request=_request(), id='chat-1', user=user, db=MagicMock())

        assert [call.args for call in mock_purge.await_args_list] == [(['child-1'],), (['child-2'],)]

    @pytest.mark.asyncio
    async def test_a_child_that_was_not_deleted_keeps_its_feedback(self):
        user = SimpleNamespace(id='owner-1', role='user')
        chat = _chat(id='chat-1', user_id='owner-1')

        with ExitStack() as stack:
            for p in self._patches(chat, lambda chat_id, user_id, db=None: chat_id != 'child-1'):
                stack.enter_context(p)
            mock_purge = stack.enter_context(
                patch.object(chats_router.Feedbacks, 'purge_feedbacks_by_chat_ids', new=AsyncMock())
            )
            result = await chats_router.delete_chat_by_id(request=_request(), id='chat-1', user=user, db=MagicMock())

        assert result is True
        assert [call.args for call in mock_purge.await_args_list] == [(['child-2'],), (['chat-1'],)]


class TestFeedbackPurgeOnDeleteAllChats:
    """Delete-all removes every chat the caller owns. The rows to purge are the caller's own
    AND anyone else's on those chats (a reader with access can rate a shared chat), so the
    ids are collected before the delete and the purge is keyed on them as well as on the user."""

    @pytest.mark.asyncio
    async def test_purges_by_the_deleted_chat_ids_and_by_the_calling_user(self):
        user = SimpleNamespace(id='user-1', role='user')

        with (
            patch.object(chats_router, 'has_permission', new=AsyncMock(return_value=True)),
            patch.object(chats_router.Config, 'get', new=AsyncMock(return_value={})),
            patch.object(
                chats_router.Chats, 'get_chat_ids_by_user_id', new=AsyncMock(return_value=['chat-a', 'chat-b'])
            ),
            patch.object(chats_router.Chats, 'delete_chats_by_user_id', new=AsyncMock(return_value=True)),
            patch.object(chats_router, 'publish_event', new=AsyncMock()),
            patch.object(chats_router, 'notify_user_chats_deleted', new=AsyncMock()),
            patch.object(chats_router.Feedbacks, 'purge_feedbacks_by_chat_ids', new=AsyncMock()) as mock_by_chat,
            patch.object(chats_router.Feedbacks, 'purge_feedbacks_by_user_id', new=AsyncMock()) as mock_by_user,
        ):
            result = await chats_router.delete_all_user_chats(request=_request(), user=user, db=MagicMock())

        assert result is True
        assert mock_by_chat.await_args.args == (['chat-a', 'chat-b'],)
        assert mock_by_user.await_args.args == ('user-1',)

    @pytest.mark.asyncio
    async def test_the_ids_are_collected_before_the_chats_are_deleted(self):
        user = SimpleNamespace(id='user-1', role='user')
        call_order = []

        async def _list(*args, **kwargs):
            call_order.append('list')
            return ['chat-a']

        async def _delete(*args, **kwargs):
            call_order.append('delete')
            return True

        async def _purge(*args, **kwargs):
            call_order.append('purge')

        with (
            patch.object(chats_router, 'has_permission', new=AsyncMock(return_value=True)),
            patch.object(chats_router.Config, 'get', new=AsyncMock(return_value={})),
            patch.object(chats_router.Chats, 'get_chat_ids_by_user_id', new=_list),
            patch.object(chats_router.Chats, 'delete_chats_by_user_id', new=_delete),
            patch.object(chats_router, 'publish_event', new=AsyncMock()),
            patch.object(chats_router, 'notify_user_chats_deleted', new=AsyncMock()),
            patch.object(chats_router.Feedbacks, 'purge_feedbacks_by_chat_ids', new=_purge),
            patch.object(chats_router.Feedbacks, 'purge_feedbacks_by_user_id', new=_purge),
        ):
            await chats_router.delete_all_user_chats(request=_request(), user=user, db=MagicMock())

        assert call_order == ['list', 'delete', 'purge', 'purge']

    @pytest.mark.asyncio
    async def test_failed_delete_purges_nothing(self):
        user = SimpleNamespace(id='user-1', role='user')

        with (
            patch.object(chats_router, 'has_permission', new=AsyncMock(return_value=True)),
            patch.object(chats_router.Config, 'get', new=AsyncMock(return_value={})),
            patch.object(chats_router.Chats, 'get_chat_ids_by_user_id', new=AsyncMock(return_value=['chat-a'])),
            patch.object(chats_router.Chats, 'delete_chats_by_user_id', new=AsyncMock(return_value=False)),
            patch.object(chats_router, 'publish_event', new=AsyncMock()),
            patch.object(chats_router, 'notify_user_chats_deleted', new=AsyncMock()),
            patch.object(chats_router.Feedbacks, 'purge_feedbacks_by_chat_ids', new=AsyncMock()) as mock_by_chat,
            patch.object(chats_router.Feedbacks, 'purge_feedbacks_by_user_id', new=AsyncMock()) as mock_by_user,
        ):
            result = await chats_router.delete_all_user_chats(request=_request(), user=user, db=MagicMock())

        assert result is False
        mock_by_chat.assert_not_awaited()
        mock_by_user.assert_not_awaited()
