"""Tests that folder deletion notifies RAGnarok for every chat it removes (path 3).

DELETE /{id} in folders.py either deletes the folder's chats (delete_contents=True,
the default) or just moves them out of the folder (delete_contents=False). Only the
former should purge PII mappings. Router functions are called directly as plain
coroutines with their module-level collaborators patched.
"""

from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from open_webui.routers import folders as folders_router


def _request():
    return MagicMock()


def _folder(id: str, user_id: str, parent_id=None):
    folder = MagicMock()
    folder.id = id
    folder.user_id = user_id
    folder.parent_id = parent_id
    return folder


def _apply_base_patches(stack: ExitStack, folder, folder_ids, chat_ids, delete_result=True, move_result=True):
    """Patch the collaborators for a single-folder (no subfolders) deletion run."""
    stack.enter_context(patch.object(folders_router, 'check_folders_permission', new=AsyncMock()))
    stack.enter_context(
        patch.object(folders_router.Folders, 'get_folder_by_id_and_user_id', new=AsyncMock(return_value=folder))
    )
    stack.enter_context(
        patch.object(
            folders_router.Folders,
            'get_folder_ids_by_id_and_user_id_in_subtree',
            new=AsyncMock(return_value=[folder.id]),
        )
    )
    stack.enter_context(
        patch.object(folders_router.Chats, 'count_chats_by_folder_ids_and_user_id', new=AsyncMock(return_value=0))
    )
    stack.enter_context(
        patch.object(folders_router.Folders, 'delete_folder_by_id_and_user_id', new=AsyncMock(return_value=folder_ids))
    )
    stack.enter_context(
        patch.object(
            folders_router.Chats, 'get_chat_ids_by_user_id_and_folder_id', new=AsyncMock(return_value=chat_ids)
        )
    )
    stack.enter_context(
        patch.object(
            folders_router.Chats,
            'delete_chats_by_user_id_and_folder_id',
            new=AsyncMock(return_value=delete_result),
        )
    )
    stack.enter_context(
        patch.object(
            folders_router.Chats, 'move_chats_by_user_id_and_folder_id', new=AsyncMock(return_value=move_result)
        )
    )
    stack.enter_context(patch.object(folders_router.AccessGrants, 'revoke_all_access', new=AsyncMock()))
    stack.enter_context(patch.object(folders_router, 'publish_event', new=AsyncMock()))
    stack.enter_context(
        patch.object(folders_router.Folders, 'get_folders_by_parent_id_and_user_id', new=AsyncMock(return_value=[]))
    )


class TestDeleteFolderContents:
    @pytest.mark.asyncio
    async def test_notifies_forget_once_per_chat_collected_before_delete(self):
        user = SimpleNamespace(id='owner-1', role='user')
        folder = _folder(id='folder-1', user_id='owner-1')

        with ExitStack() as stack:
            _apply_base_patches(stack, folder, folder_ids=['folder-1'], chat_ids=['chat-a', 'chat-b'])
            mock_notify = stack.enter_context(patch.object(folders_router, 'notify_chat_deleted', new=AsyncMock()))

            result = await folders_router.delete_folder_by_id(
                request=_request(), id='folder-1', delete_contents=True, user=user, db=MagicMock()
            )

        assert result is True
        assert mock_notify.await_args_list == [
            (('owner-1', 'chat-a'),),
            (('owner-1', 'chat-b'),),
        ]

    @pytest.mark.asyncio
    async def test_chat_ids_are_collected_before_the_delete_call(self):
        """Chat ids must be listed before delete_chats_by_user_id_and_folder_id runs --
        afterwards the rows are gone and there is nothing left to list. Uses a shared
        call-order tracker rather than fixed return values, so reversing the two calls
        in the source would be caught even though both are otherwise mocked."""
        user = SimpleNamespace(id='owner-1', role='user')
        folder = _folder(id='folder-1', user_id='owner-1')
        call_order = []

        async def _get_ids(*args, **kwargs):
            call_order.append('get_chat_ids')
            return ['chat-a']

        async def _delete(*args, **kwargs):
            call_order.append('delete_chats')
            return True

        with ExitStack() as stack:
            _apply_base_patches(stack, folder, folder_ids=['folder-1'], chat_ids=['chat-a'])
            stack.enter_context(
                patch.object(folders_router.Chats, 'get_chat_ids_by_user_id_and_folder_id', new=_get_ids)
            )
            stack.enter_context(
                patch.object(folders_router.Chats, 'delete_chats_by_user_id_and_folder_id', new=_delete)
            )
            stack.enter_context(patch.object(folders_router, 'notify_chat_deleted', new=AsyncMock()))

            await folders_router.delete_folder_by_id(
                request=_request(), id='folder-1', delete_contents=True, user=user, db=MagicMock()
            )

        assert call_order == ['get_chat_ids', 'delete_chats']

    @pytest.mark.asyncio
    async def test_does_not_notify_when_chat_deletion_fails(self):
        user = SimpleNamespace(id='owner-1', role='user')
        folder = _folder(id='folder-1', user_id='owner-1')

        with ExitStack() as stack:
            _apply_base_patches(
                stack, folder, folder_ids=['folder-1'], chat_ids=['chat-a', 'chat-b'], delete_result=False
            )
            mock_notify = stack.enter_context(patch.object(folders_router, 'notify_chat_deleted', new=AsyncMock()))

            result = await folders_router.delete_folder_by_id(
                request=_request(), id='folder-1', delete_contents=True, user=user, db=MagicMock()
            )

        assert result is True  # folder deletion itself still "succeeds"
        mock_notify.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_does_not_notify_when_chats_are_moved_not_deleted(self):
        """delete_contents=False moves chats out of the folder instead of deleting
        them -- nothing was actually removed, so no mapping should be purged."""
        user = SimpleNamespace(id='owner-1', role='user')
        folder = _folder(id='folder-1', user_id='owner-1')

        with ExitStack() as stack:
            _apply_base_patches(stack, folder, folder_ids=['folder-1'], chat_ids=['chat-a'])
            mock_notify = stack.enter_context(patch.object(folders_router, 'notify_chat_deleted', new=AsyncMock()))

            result = await folders_router.delete_folder_by_id(
                request=_request(), id='folder-1', delete_contents=False, user=user, db=MagicMock()
            )

        assert result is True
        mock_notify.assert_not_awaited()
