"""ChatTable.get_chat_ids_by_user_id: every chat id a user owns, collected BEFORE a bulk delete.

Delete-all-my-chats and user delete remove every chat the user owns. Feedback rows written by
OTHER users (anyone with read access can rate a shared chat) carry a snapshot of those chats
too, so the delete paths need the ids to purge them by chat. Like its folder sibling it fails
safe: it runs on a delete path and must not turn a survivable blip into an error response.
Runs against a real in-memory SQLite ``chat`` table, so "no filtering" is exercised as SQL.
"""

from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from open_webui.models import chats as chats_module
from open_webui.models.chats import Chat, Chats


@pytest_asyncio.fixture
async def chat_db():
    engine = create_async_engine('sqlite+aiosqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    async with engine.begin() as conn:
        await conn.run_sync(Chat.__table__.create)
    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def _context(db=None):
        async with maker() as session:
            yield session

    with patch.object(chats_module, 'get_async_db_context', _context):
        yield maker
    await engine.dispose()


async def _add(maker, id, user_id, **kw):
    async with maker() as session:
        session.add(Chat(id=id, user_id=user_id, title='Synthetic chat', chat={}, created_at=1, updated_at=1, **kw))
        await session.commit()


class TestGetChatIdsByUserId:
    @pytest.mark.asyncio
    async def test_returns_every_chat_the_user_owns_and_no_one_elses(self, chat_db):
        await _add(chat_db, 'c-plain', 'owner-1')
        await _add(chat_db, 'c-archived', 'owner-1', archived=True)
        await _add(chat_db, 'c-pinned', 'owner-1', pinned=True)
        await _add(chat_db, 'c-foldered', 'owner-1', folder_id='folder-1')
        await _add(chat_db, 'c-internal', 'owner-1', meta={'internal': True})
        await _add(chat_db, 'c-other', 'owner-2')

        assert sorted(await Chats.get_chat_ids_by_user_id('owner-1')) == [
            'c-archived',
            'c-foldered',
            'c-internal',
            'c-pinned',
            'c-plain',
        ]

    @pytest.mark.asyncio
    async def test_a_user_with_no_chats_gets_an_empty_list(self, chat_db):
        assert await Chats.get_chat_ids_by_user_id('owner-1') == []

    @pytest.mark.asyncio
    async def test_a_database_failure_returns_empty_instead_of_raising(self):
        with patch.object(chats_module, 'get_async_db_context', side_effect=Exception('connection already closed')):
            assert await Chats.get_chat_ids_by_user_id('owner-1') == []
