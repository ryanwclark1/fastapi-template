"""Tests for the reminders service layer."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytest.importorskip("dateutil.rrule", reason="Reminder schemas require python-dateutil")

from example_service.features.reminders.models import Reminder
from example_service.features.reminders.schemas import ReminderCreate
from example_service.features.reminders.service import ReminderService
from example_service.features.tags.models import Tag, reminder_tags


@pytest.fixture
async def session() -> AsyncSession:
    """Provide an isolated in-memory database session."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    tables = [Reminder.__table__, Tag.__table__, reminder_tags]
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: Reminder.metadata.create_all(sync_conn, tables=tables))

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_create_and_list_reminders(session: AsyncSession) -> None:
    service = ReminderService(session)

    await service.create_reminder(ReminderCreate(title="Pay bills"))
    reminders = await service.list_reminders()

    assert len(reminders) == 1
    assert reminders[0].title == "Pay bills"


@pytest.mark.asyncio
async def test_get_reminder_round_trip(session: AsyncSession) -> None:
    service = ReminderService(session)

    created = await service.create_reminder(ReminderCreate(title="Submit report"))
    fetched = await service.get_reminder(created.id)

    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.title == "Submit report"


@pytest.mark.asyncio
async def test_mark_completed_and_notification(session: AsyncSession) -> None:
    service = ReminderService(session)

    reminder = await service.create_reminder(ReminderCreate(title="Call mom"))
    assert reminder.is_completed is False
    assert reminder.notification_sent is False

    completed = await service.mark_completed(reminder.id)
    assert completed is not None and completed.is_completed

    notified = await service.mark_notification_sent(reminder.id)
    assert notified is not None and notified.notification_sent
