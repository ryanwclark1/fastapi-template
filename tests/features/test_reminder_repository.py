"""Integration-style tests for the reminder repository queries."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytest.importorskip("dateutil.rrule", reason="Reminder models require python-dateutil")

from example_service.features.reminders.models import Reminder
from example_service.features.reminders.repository import ReminderRepository
from example_service.features.tags.models import Tag, reminder_tags


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Provide an isolated in-memory database session."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    tables = [Reminder.__table__, Tag.__table__, reminder_tags]
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Reminder.metadata.create_all(sync_conn, tables=tables)
        )

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session

    await engine.dispose()


async def _persist(session: AsyncSession, **kwargs) -> Reminder:
    reminder = Reminder(**kwargs)
    session.add(reminder)
    await session.commit()
    await session.refresh(reminder)
    return reminder


@pytest.mark.asyncio
async def test_find_pending_excludes_completed(session: AsyncSession) -> None:
    repo = ReminderRepository()
    await _persist(session, title="active", is_completed=False)
    await _persist(session, title="done", is_completed=True)

    pending = await repo.find_pending(session)

    assert len(pending) == 1
    assert pending[0].title == "active"


@pytest.mark.asyncio
async def test_find_overdue_filters_by_time(session: AsyncSession) -> None:
    repo = ReminderRepository()
    now = datetime.now(UTC)
    await _persist(
        session,
        title="overdue",
        remind_at=now - timedelta(hours=1),
        is_completed=False,
    )
    await _persist(
        session,
        title="future",
        remind_at=now + timedelta(hours=1),
        is_completed=False,
    )

    overdue = await repo.find_overdue(session, as_of=now)

    assert [item.title for item in overdue] == ["overdue"]


@pytest.mark.asyncio
async def test_find_pending_notifications_respects_sent_flag(session: AsyncSession) -> None:
    repo = ReminderRepository()
    now = datetime.now(UTC)
    await _persist(
        session,
        title="notify",
        remind_at=now,
        is_completed=False,
        notification_sent=False,
    )
    await _persist(
        session,
        title="already_sent",
        remind_at=now,
        is_completed=False,
        notification_sent=True,
    )

    pending = await repo.find_pending_notifications(session, as_of=now)

    assert len(pending) == 1
    assert pending[0].title == "notify"


@pytest.mark.asyncio
async def test_search_reminders_supports_filters(session: AsyncSession) -> None:
    repo = ReminderRepository()
    now = datetime.now(UTC)
    await _persist(session, title="groceries", description="buy milk", created_at=now)
    await _persist(
        session,
        title="secret",
        description="hidden",
        created_at=now - timedelta(days=2),
        is_completed=True,
    )

    result = await repo.search_reminders(
        session,
        query="milk",
        include_completed=False,
        after=now - timedelta(hours=1),
        limit=10,
    )

    assert result.total == 1
    assert result.items[0].title == "groceries"
