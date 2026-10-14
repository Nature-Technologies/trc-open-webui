"""FeedbackTable.purge_feedbacks_by_chat_ids / purge_feedbacks_by_user_id.

A feedback row's ``snapshot`` is a full copy of the chat it rates, with the restored
(unmasked) answers in it. These purges are what the chat-destroy paths call so a rating
never outlives its chat. They run against a real in-memory SQLite database (the
``feedback`` table only), so the JSON ``meta.chat_id`` filter is exercised as SQL, not
mocked.
"""

from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from open_webui.models import feedbacks as feedbacks_module
from open_webui.models.feedbacks import Feedback, Feedbacks


@pytest_asyncio.fixture
async def feedback_db():
    engine = create_async_engine('sqlite+aiosqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    async with engine.begin() as conn:
        await conn.run_sync(Feedback.__table__.create)
    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def _context(db=None):
        async with maker() as session:
            yield session

    with patch.object(feedbacks_module, 'get_async_db_context', _context):
        yield maker
    await engine.dispose()


async def _add(maker, id, user_id, chat_id):
    async with maker() as session:
        session.add(
            Feedback(
                id=id,
                user_id=user_id,
                version=0,
                type='rating',
                data={'rating': 1, 'model_id': 'hermes'},
                meta={'chat_id': chat_id, 'message_id': 'm1'} if chat_id else {'arena': False},
                snapshot={'chat': {'title': 'Synthetic chat', 'history': {'messages': {}}}},
                created_at=1,
                updated_at=1,
            )
        )
        await session.commit()


async def _ids(maker):
    async with maker() as session:
        return sorted((await session.execute(select(Feedback.id))).scalars().all())


class TestPurgeByChatIds:
    @pytest.mark.asyncio
    async def test_deletes_every_row_for_those_chats_whoever_wrote_it(self, feedback_db):
        await _add(feedback_db, 'f1', 'owner-1', 'chat-a')
        await _add(feedback_db, 'f2', 'admin-1', 'chat-a')
        await _add(feedback_db, 'f3', 'owner-1', 'chat-b')
        await _add(feedback_db, 'f4', 'owner-1', None)

        deleted = await Feedbacks.purge_feedbacks_by_chat_ids(['chat-a'])

        assert deleted == 2
        assert await _ids(feedback_db) == ['f3', 'f4']

    @pytest.mark.asyncio
    async def test_several_chats_at_once(self, feedback_db):
        await _add(feedback_db, 'f1', 'owner-1', 'chat-a')
        await _add(feedback_db, 'f2', 'owner-1', 'chat-b')
        await _add(feedback_db, 'f3', 'owner-1', 'chat-c')

        assert await Feedbacks.purge_feedbacks_by_chat_ids(['chat-a', 'chat-c', 'chat-a']) == 2
        assert await _ids(feedback_db) == ['f2']

    @pytest.mark.asyncio
    async def test_a_large_folder_is_purged_completely(self, feedback_db):
        """More ids than one SQL statement's variable limit on an old SQLite."""
        await _add(feedback_db, 'f-first', 'owner-1', 'chat-0')
        await _add(feedback_db, 'f-last', 'owner-1', 'chat-1199')
        await _add(feedback_db, 'f-other', 'owner-1', 'chat-elsewhere')

        deleted = await Feedbacks.purge_feedbacks_by_chat_ids([f'chat-{i}' for i in range(1200)])

        assert deleted == 2
        assert await _ids(feedback_db) == ['f-other']

    @pytest.mark.asyncio
    @pytest.mark.parametrize('chat_ids', [[], [None, ''], None])
    async def test_nothing_to_purge_deletes_nothing(self, feedback_db, chat_ids):
        await _add(feedback_db, 'f1', 'owner-1', 'chat-a')
        await _add(feedback_db, 'f2', 'owner-1', None)

        assert await Feedbacks.purge_feedbacks_by_chat_ids(chat_ids) == 0
        assert await _ids(feedback_db) == ['f1', 'f2']


class TestPurgeByUserId:
    @pytest.mark.asyncio
    async def test_deletes_only_that_users_rows(self, feedback_db):
        await _add(feedback_db, 'f1', 'user-1', 'chat-a')
        await _add(feedback_db, 'f2', 'user-1', None)
        await _add(feedback_db, 'f3', 'user-2', 'chat-b')

        assert await Feedbacks.purge_feedbacks_by_user_id('user-1') == 2
        assert await _ids(feedback_db) == ['f3']

    @pytest.mark.asyncio
    async def test_empty_user_id_deletes_nothing(self, feedback_db):
        await _add(feedback_db, 'f1', 'user-1', 'chat-a')

        assert await Feedbacks.purge_feedbacks_by_user_id('') == 0
        assert await _ids(feedback_db) == ['f1']


class TestPurgeNeverRaises:
    """Both run after the chat delete has committed: a DB blip must not turn a
    successful deletion into an error response."""

    @pytest.mark.asyncio
    async def test_chat_purge_reports_zero_on_db_failure(self):
        with patch.object(feedbacks_module, 'get_async_db_context', side_effect=Exception('db down')):
            assert await Feedbacks.purge_feedbacks_by_chat_ids(['chat-a']) == 0

    @pytest.mark.asyncio
    async def test_user_purge_reports_zero_on_db_failure(self):
        with patch.object(feedbacks_module, 'get_async_db_context', side_effect=Exception('db down')):
            assert await Feedbacks.purge_feedbacks_by_user_id('user-1') == 0
