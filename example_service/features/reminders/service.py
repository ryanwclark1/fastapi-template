"""Service layer for reminder-specific business logic."""
from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from example_service.core.services.base import BaseService
from example_service.features.reminders.models import Reminder
from example_service.features.reminders.repository import (
    ReminderRepository,
    get_reminder_repository,
)
from example_service.features.reminders.schemas import ReminderCreate

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class ReminderService(BaseService):
    """Orchestrates reminder operations using the repository."""

    def __init__(
        self,
        session: AsyncSession,
        repository: ReminderRepository | None = None,
    ) -> None:
        super().__init__()
        self._session = session
        self._repository = repository or get_reminder_repository()

    async def create_reminder(self, payload: ReminderCreate) -> Reminder:
        """Create and persist a new reminder from user input."""
        reminder_data = payload.model_dump(exclude={"recurrence"})
        reminder = Reminder(**reminder_data)
        created = await self._repository.create(self._session, reminder)

        # INFO level - business event (audit trail)
        self.logger.info(
            "Reminder created",
            extra={
                "reminder_id": str(created.id),
                "title": payload.title[:50] if payload.title else None,
                "has_remind_at": payload.remind_at is not None,
                "operation": "service.create_reminder",
            },
        )
        return created

    async def list_reminders(self, *, limit: int = 100, offset: int = 0) -> list[Reminder]:
        """List reminders with pagination defaults."""
        reminders = await self._repository.list(
            self._session,
            limit=limit,
            offset=offset,
        )
        result = list(reminders)

        # DEBUG level - routine list operation
        self._lazy.debug(
            lambda: f"service.list_reminders(limit={limit}, offset={offset}) -> {len(result)} items"
        )
        return result

    async def get_reminder(self, reminder_id: UUID) -> Reminder | None:
        """Fetch a reminder by id without raising if it is missing."""
        reminder = await self._repository.get(self._session, reminder_id)

        # DEBUG level - routine get
        self._lazy.debug(
            lambda: f"service.get_reminder({reminder_id}) -> {'found' if reminder else 'not found'}"
        )
        return reminder

    async def mark_completed(self, reminder_id: UUID) -> Reminder | None:
        """Mark a reminder as completed if it exists."""
        result = await self._repository.mark_completed(self._session, reminder_id)

        if result:
            # INFO level - state transition (business event)
            self.logger.info(
                "Reminder marked completed",
                extra={"reminder_id": str(reminder_id), "operation": "service.mark_completed"},
            )
        else:
            # DEBUG level - expected "not found" case
            self._lazy.debug(
                lambda: f"service.mark_completed({reminder_id}) -> not found"
            )
        return result

    async def mark_notification_sent(self, reminder_id: UUID) -> Reminder | None:
        """Mark that a reminder's notification has been sent."""
        result = await self._repository.mark_notification_sent(self._session, reminder_id)

        if result:
            # INFO level - notification lifecycle event
            self.logger.info(
                "Notification sent for reminder",
                extra={"reminder_id": str(reminder_id), "operation": "service.mark_notification_sent"},
            )
        else:
            self._lazy.debug(
                lambda: f"service.mark_notification_sent({reminder_id}) -> not found"
            )
        return result


__all__ = ["ReminderService"]
