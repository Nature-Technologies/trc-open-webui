"""Tests that ChatTable.get_chat_ids_by_user_id_and_folder_id fails safe.

It is read-only bookkeeping for the RAGnarok purge, but it runs on the folder
deletion path after the folder rows are already committed, so a raise here
would turn a survivable blip into HTTP 400 with the folders gone, the chats
orphaned and the access grants never revoked. Its write-side siblings
(delete_chats_by_user_id_and_folder_id, move_chats_by_user_id_and_folder_id,
delete_chats_by_user_id) all swallow and return a safe default; so must this.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from open_webui.models.chats import Chats


class _FakeSessionContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class TestGetChatIdsByUserIdAndFolderId:
    @pytest.mark.asyncio
    async def test_returns_the_ids_when_the_query_succeeds(self):
        result = MagicMock()
        result.all.return_value = [('chat-a',), ('chat-b',)]
        session = MagicMock()
        session.execute = AsyncMock(return_value=result)

        with patch(
            'open_webui.models.chats.get_async_db_context',
            return_value=_FakeSessionContext(session),
        ):
            chat_ids = await Chats.get_chat_ids_by_user_id_and_folder_id('owner-1', 'folder-1')

        assert chat_ids == ['chat-a', 'chat-b']

    @pytest.mark.asyncio
    async def test_statement_failure_returns_empty_instead_of_raising(self):
        """A statement timeout on the SELECT itself."""
        session = MagicMock()
        session.execute = AsyncMock(side_effect=Exception('canceling statement due to statement timeout'))

        with patch(
            'open_webui.models.chats.get_async_db_context',
            return_value=_FakeSessionContext(session),
        ):
            chat_ids = await Chats.get_chat_ids_by_user_id_and_folder_id('owner-1', 'folder-1')

        assert chat_ids == []

    @pytest.mark.asyncio
    async def test_connection_failure_returns_empty_instead_of_raising(self):
        """A blip acquiring the session at all, before any statement runs."""
        with patch(
            'open_webui.models.chats.get_async_db_context',
            side_effect=Exception('connection already closed'),
        ):
            chat_ids = await Chats.get_chat_ids_by_user_id_and_folder_id('owner-1', 'folder-1')

        assert chat_ids == []
