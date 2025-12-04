"""Tests for the reminders service layer."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

pytest.importorskip("dateutil.rrule", reason="Reminder schemas require python-dateutil")

from example_service.features.reminders.schemas import ReminderCreate
from example_service.features.reminders.service import ReminderService


@pytest.mark.asyncio
async def test_create_and_list_reminders(db_session: AsyncSession) -> None:
    service = ReminderService(db_session)

    await service.create_reminder(ReminderCreate(title="Pay bills"))
    reminders = await service.list_reminders()

    assert len(reminders) == 1
    assert reminders[0].title == "Pay bills"


@pytest.mark.asyncio
async def test_get_reminder_round_trip(db_session: AsyncSession) -> None:
    service = ReminderService(db_session)

    created = await service.create_reminder(ReminderCreate(title="Submit report"))
    fetched = await service.get_reminder(created.id)

    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.title == "Submit report"


@pytest.mark.asyncio
async def test_mark_completed_and_notification(db_session: AsyncSession) -> None:
    service = ReminderService(db_session)

    reminder = await service.create_reminder(ReminderCreate(title="Call mom"))
    assert reminder.is_completed is False
    assert reminder.notification_sent is False

    completed = await service.mark_completed(reminder.id)
    assert completed is not None
    assert completed.is_completed

    notified = await service.mark_notification_sent(reminder.id)
    assert notified is not None
    assert notified.notification_sent
