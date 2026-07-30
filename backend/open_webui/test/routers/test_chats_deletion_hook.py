"""Tests that chat-deletion routes notify RAGnarok correctly.

Covers the two call sites for path 1 (single-chat DELETE /{id}, admin and
owner branches) and path 2 (DELETE /, delete-all-of-my-chats) described in
the deletion-hook task. Router functions are invoked directly as plain
coroutines (FastAPI's @router.delete decorator returns the undecorated
function), with their module-level collaborators patched, so no live app,
DB, or network is needed.
"""

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
