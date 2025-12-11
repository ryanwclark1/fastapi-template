"""Integration-style tests for the reminder repository queries."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("dateutil.rrule", reason="Reminder models require python-dateutil")

from example_service.features.reminders.models import Reminder
from example_service.features.reminders.repository import ReminderRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def _persist(db_session: AsyncSession, **kwargs) -> Reminder:
    reminder = Reminder(**kwargs)
    db_session.add(reminder)
    await db_session.commit()
    await db_session.refresh(reminder)
    return reminder


@pytest.mark.asyncio
async def test_find_pending_excludes_completed(db_session: AsyncSession) -> None:
    repo = ReminderRepository()
    await _persist(db_session, title="active", is_completed=False)
    await _persist(db_session, title="done", is_completed=True)

    pending = await repo.find_pending(db_session)

    assert len(pending) == 1
    assert pending[0].title == "active"


@pytest.mark.asyncio
async def test_find_overdue_filters_by_time(db_session: AsyncSession) -> None:
    repo = ReminderRepository()
    now = datetime.now(UTC)
    await _persist(
        db_session,
        title="overdue",
        remind_at=now - timedelta(hours=1),
        is_completed=False,
    )
    await _persist(
        db_session,
        title="future",
        remind_at=now + timedelta(hours=1),
        is_completed=False,
    )

    overdue = await repo.find_overdue(db_session, as_of=now)

    assert [item.title for item in overdue] == ["overdue"]


@pytest.mark.asyncio
async def test_find_pending_notifications_respects_sent_flag(db_session: AsyncSession) -> None:
    repo = ReminderRepository()
    now = datetime.now(UTC)
    await _persist(
        db_session,
        title="notify",
        remind_at=now,
        is_completed=False,
        notification_sent=False,
    )
    await _persist(
        db_session,
        title="already_sent",
        remind_at=now,
        is_completed=False,
        notification_sent=True,
    )

    pending = await repo.find_pending_notifications(db_session, as_of=now)

    assert len(pending) == 1
    assert pending[0].title == "notify"


@pytest.mark.asyncio
async def test_search_reminders_supports_filters(db_session: AsyncSession) -> None:
    repo = ReminderRepository()
    now = datetime.now(UTC)
    await _persist(db_session, title="groceries", description="buy milk", created_at=now)
    await _persist(
        db_session,
        title="secret",
        description="hidden",
        created_at=now - timedelta(days=2),
        is_completed=True,
    )

    result = await repo.search_reminders(
        db_session,
        query="milk",
        include_completed=False,
        after=now - timedelta(hours=1),
        limit=10,
    )

    assert result.total == 1
    assert result.items[0].title == "groceries"
