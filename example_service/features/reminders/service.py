"""Service layer for the reminders feature."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from example_service.core.services.base import BaseService
from example_service.features.reminders.models import Reminder
from example_service.features.reminders.schemas import ReminderCreate


class ReminderService(BaseService):
    """Business logic for managing reminders."""

    def __init__(self, session: AsyncSession):
        super().__init__()
        self._session = session

    async def list_reminders(self) -> list[Reminder]:
        """Return all reminders sorted by creation date."""
        result = await self._session.execute(
            select(Reminder).order_by(Reminder.created_at.desc()),
        )
        return list(result.scalars().all())

    async def get_reminder(self, reminder_id: UUID) -> Reminder | None:
        """Fetch a reminder by its identifier."""
        return await self._session.get(Reminder, reminder_id)

    async def create_reminder(self, payload: ReminderCreate) -> Reminder:
        """Persist a new reminder."""
        reminder = Reminder(
            title=payload.title,
            description=payload.description,
            remind_at=payload.remind_at,
        )
        self._session.add(reminder)
        await self._session.commit()
        await self._session.refresh(reminder)
        return reminder
