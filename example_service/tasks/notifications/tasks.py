"""Reminder notification task definitions.

This module provides:
- Periodic checking for due reminders
- Notification sending (extensible to email, webhook, push)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select, update

from example_service.infra.database.session import get_async_session
from example_service.tasks.broker import broker

logger = logging.getLogger(__name__)


if broker is not None:

    @broker.task()
    async def check_due_reminders() -> dict:
        """Check for reminders that are due and trigger notifications.

        Scheduled: Every 1 minute (via APScheduler).

        Queries reminders where:
        - remind_at <= now
        - is_completed = False
        - notification_sent = False

        Returns:
            Dictionary with count of due reminders and triggered notifications.

        Example:
            ```python
            from example_service.tasks.notifications import check_due_reminders
            task = await check_due_reminders.kiq()
            result = await task.wait_result()
            print(result)
            # {'due_count': 3, 'notification_tasks': ['task-id-1', ...]}
            ```
        """
        from example_service.features.reminders.models import Reminder

        async with get_async_session() as session:
            now = datetime.now(timezone.utc)

            # Find due reminders that haven't been notified
            stmt = select(Reminder).where(
                Reminder.remind_at <= now,
                Reminder.is_completed == False,  # noqa: E712
                Reminder.notification_sent == False,  # noqa: E712
            )
            result = await session.execute(stmt)
            due_reminders = result.scalars().all()

            if not due_reminders:
                logger.debug("No due reminders found")
                return {"due_count": 0, "notification_tasks": []}

            logger.info(
                "Found due reminders",
                extra={"count": len(due_reminders)},
            )

            # Trigger notification for each and mark as sent
            notification_tasks = []
            reminder_ids = []

            for reminder in due_reminders:
                task = await send_reminder_notification.kiq(
                    reminder_id=str(reminder.id),
                    title=reminder.title,
                    description=reminder.description,
                )
                notification_tasks.append(task.task_id)
                reminder_ids.append(reminder.id)

            # Batch update notification_sent flag
            if reminder_ids:
                update_stmt = (
                    update(Reminder)
                    .where(Reminder.id.in_(reminder_ids))
                    .values(notification_sent=True)
                )
                await session.execute(update_stmt)
                await session.commit()

            return {
                "due_count": len(due_reminders),
                "notification_tasks": notification_tasks,
            }

    @broker.task(retry_on_error=True, max_retries=3)
    async def send_reminder_notification(
        reminder_id: str,
        title: str,
        description: str | None = None,
    ) -> dict:
        """Send notification for a specific reminder.

        Extensible notification channels:
        - Log (default, always active)
        - Email (if configured)
        - Webhook (if configured)
        - Push notification (future)

        Args:
            reminder_id: UUID of the reminder.
            title: Reminder title.
            description: Optional reminder description.

        Returns:
            Notification status dictionary.
        """
        logger.info(
            "REMINDER DUE: %s",
            title,
            extra={
                "reminder_id": reminder_id,
                "description": description,
                "notification_type": "reminder",
            },
        )

        channels_sent = ["log"]

        # TODO: Add email notification
        # from example_service.tasks.tasks import send_email_task
        # if user_email:
        #     await send_email_task.kiq(
        #         to=user_email,
        #         subject=f"Reminder: {title}",
        #         body=description or title,
        #     )
        #     channels_sent.append("email")

        # TODO: Add webhook notification
        # if webhook_url:
        #     await notify_webhook.kiq(
        #         url=webhook_url,
        #         payload={"reminder_id": reminder_id, "title": title},
        #     )
        #     channels_sent.append("webhook")

        return {
            "status": "sent",
            "reminder_id": reminder_id,
            "title": title,
            "channels": channels_sent,
        }

    @broker.task()
    async def mark_reminder_completed(reminder_id: str) -> dict:
        """Mark a reminder as completed.

        Args:
            reminder_id: UUID of the reminder to complete.

        Returns:
            Update status.
        """
        from uuid import UUID

        from example_service.features.reminders.models import Reminder

        try:
            uuid_id = UUID(reminder_id)
        except ValueError:
            return {"status": "error", "reason": "invalid_uuid"}

        async with get_async_session() as session:
            stmt = (
                update(Reminder)
                .where(Reminder.id == uuid_id)
                .values(is_completed=True)
            )
            result = await session.execute(stmt)
            await session.commit()

            if result.rowcount == 0:
                return {"status": "not_found", "reminder_id": reminder_id}

            logger.info(
                "Reminder marked as completed",
                extra={"reminder_id": reminder_id},
            )

            return {"status": "completed", "reminder_id": reminder_id}
