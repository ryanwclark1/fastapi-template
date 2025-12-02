"""Notification task definitions.

This module provides:
- Periodic checking for due reminders
- Email notification sending
- Template-based email delivery
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update

from example_service.core.settings import get_email_settings
from example_service.infra.database.session import get_async_session
from example_service.infra.email import get_email_service
from example_service.infra.email.schemas import EmailPriority
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
                from example_service.tasks.notifications import check_due_reminders
            task = await check_due_reminders.kiq()
            result = await task.wait_result()
            print(result)
            # {'due_count': 3, 'notification_tasks': ['task-id-1', ...]}
        """
        from example_service.features.reminders.models import Reminder

        async with get_async_session() as session:
            now = datetime.now(UTC)

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
                    user_email=getattr(reminder, "user_email", None),
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
        user_email: str | None = None,
    ) -> dict:
        """Send notification for a specific reminder.

        Notification channels (in order of preference):
        - Email (if email is configured and user_email provided)
        - Log (always active as fallback)

        Args:
            reminder_id: UUID of the reminder.
            title: Reminder title.
            description: Optional reminder description.
            user_email: Optional user email for email notification.

        Returns:
            Notification status dictionary.
        """
        channels_sent = []
        email_result = None

        # Check if email is enabled and configured
        email_settings = get_email_settings()

        if email_settings.enabled and user_email:
            try:
                email_service = get_email_service()
                result = await email_service.send_template(
                    to=user_email,
                    template="reminder",
                    subject=f"Reminder: {title}",
                    context={
                        "title": title,
                        "description": description,
                        "reminder_id": reminder_id,
                    },
                )
                if result.success:
                    channels_sent.append("email")
                    email_result = {
                        "message_id": result.message_id,
                        "status": result.status.value,
                    }
                    logger.info(
                        "Reminder email sent",
                        extra={
                            "reminder_id": reminder_id,
                            "email": user_email,
                            "message_id": result.message_id,
                        },
                    )
                else:
                    logger.warning(
                        "Failed to send reminder email",
                        extra={
                            "reminder_id": reminder_id,
                            "email": user_email,
                            "error": result.error,
                        },
                    )
            except Exception as e:
                logger.exception(f"Error sending reminder email: {e}")

        # Always log the reminder (fallback notification)
        logger.info(
            "REMINDER DUE: %s",
            title,
            extra={
                "reminder_id": reminder_id,
                "description": description,
                "notification_type": "reminder",
                "user_email": user_email,
            },
        )
        channels_sent.append("log")

        return {
            "status": "sent",
            "reminder_id": reminder_id,
            "title": title,
            "channels": channels_sent,
            "email_result": email_result,
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
            stmt = update(Reminder).where(Reminder.id == uuid_id).values(is_completed=True)
            result = await session.execute(stmt)
            await session.commit()

            if result.rowcount == 0:  # type: ignore[attr-defined]
                return {"status": "not_found", "reminder_id": reminder_id}

            logger.info(
                "Reminder marked as completed",
                extra={"reminder_id": reminder_id},
            )

            return {"status": "completed", "reminder_id": reminder_id}

    # ==========================================================================
    # Email Tasks for Queue-Based Delivery
    # ==========================================================================

    @broker.task(retry_on_error=True, max_retries=3)
    async def send_email_task(
        to: list[str],
        subject: str,
        body: str | None = None,
        body_html: str | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        reply_to: str | None = None,
        from_email: str | None = None,
        from_name: str | None = None,
        priority: str = "normal",
        headers: dict[str, str] | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict:
        """Send an email via background task.

        This task is used for queue-based email delivery, allowing emails
        to be sent asynchronously without blocking the request.

        Args:
            to: Recipient email addresses.
            subject: Email subject.
            body: Plain text body.
            body_html: HTML body.
            cc: CC recipients.
            bcc: BCC recipients.
            reply_to: Reply-to address.
            from_email: Sender email.
            from_name: Sender name.
            priority: Email priority (low, normal, high).
            headers: Additional headers.
            tags: Tags for tracking.
            metadata: Custom metadata.

        Returns:
            Dictionary with send result.
        """
        email_service = get_email_service()

        # Convert priority string to enum
        priority_enum = EmailPriority(priority)

        result = await email_service.send(
            to=to,
            subject=subject,
            body=body,
            body_html=body_html,
            cc=cc,
            bcc=bcc,
            reply_to=reply_to,
            from_email=from_email,
            from_name=from_name,
            priority=priority_enum,
            headers=headers,
            tags=tags,
            metadata=metadata,
        )

        return {
            "success": result.success,
            "message_id": result.message_id,
            "status": result.status.value,
            "error": result.error,
            "recipients_accepted": result.recipients_accepted,
            "recipients_rejected": result.recipients_rejected,
        }

    @broker.task(retry_on_error=True, max_retries=3)
    async def send_template_email_task(
        to: list[str],
        template: str,
        context: dict[str, Any] | None = None,
        subject: str | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        reply_to: str | None = None,
        from_email: str | None = None,
        from_name: str | None = None,
        priority: str = "normal",
        headers: dict[str, str] | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict:
        """Send a template email via background task.

        This task renders an email template and sends it asynchronously.

        Args:
            to: Recipient email addresses.
            template: Template name (without extension).
            context: Template context variables.
            subject: Subject override.
            cc: CC recipients.
            bcc: BCC recipients.
            reply_to: Reply-to address.
            from_email: Sender email.
            from_name: Sender name.
            priority: Email priority (low, normal, high).
            headers: Additional headers.
            tags: Tags for tracking.
            metadata: Custom metadata.

        Returns:
            Dictionary with send result.
        """
        email_service = get_email_service()

        # Convert priority string to enum
        priority_enum = EmailPriority(priority)

        try:
            result = await email_service.send_template(
                to=to,
                template=template,
                context=context,
                subject=subject,
                cc=cc,
                bcc=bcc,
                reply_to=reply_to,
                from_email=from_email,
                from_name=from_name,
                priority=priority_enum,
                headers=headers,
                tags=tags,
                metadata=metadata,
            )

            return {
                "success": result.success,
                "message_id": result.message_id,
                "status": result.status.value,
                "error": result.error,
                "recipients_accepted": result.recipients_accepted,
                "recipients_rejected": result.recipients_rejected,
                "template": template,
            }
        except Exception as e:
            logger.exception(f"Failed to send template email: {e}")
            return {
                "success": False,
                "error": str(e),
                "template": template,
            }

    @broker.task()
    async def send_batch_emails_task(
        emails: list[dict[str, Any]],
    ) -> dict:
        """Send multiple emails in batch.

        Args:
            emails: List of email dictionaries with keys:
                - to, subject, body/body_html, etc.

        Returns:
            Dictionary with batch results.
        """
        email_service = get_email_service()

        results = []
        success_count = 0
        failure_count = 0

        for email_data in emails:
            try:
                result = await email_service.send(
                    to=email_data["to"],
                    subject=email_data["subject"],
                    body=email_data.get("body"),
                    body_html=email_data.get("body_html"),
                    cc=email_data.get("cc"),
                    bcc=email_data.get("bcc"),
                    reply_to=email_data.get("reply_to"),
                )
                results.append({
                    "to": email_data["to"],
                    "success": result.success,
                    "message_id": result.message_id,
                })
                if result.success:
                    success_count += 1
                else:
                    failure_count += 1
            except Exception as e:
                results.append({
                    "to": email_data.get("to"),
                    "success": False,
                    "error": str(e),
                })
                failure_count += 1

        return {
            "total": len(emails),
            "success_count": success_count,
            "failure_count": failure_count,
            "results": results,
        }
