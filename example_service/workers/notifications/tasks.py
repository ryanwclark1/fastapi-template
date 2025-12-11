"""Notification task definitions.

This module provides:
- Periodic checking for due reminders
- Email notification sending
- Template-based email delivery
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select, update

from example_service.core.settings import get_email_settings
from example_service.features.notifications.channels.dispatcher import (
    get_notification_dispatcher,
)
from example_service.features.notifications.metrics import (
    notification_retry_exhausted_total,
    notification_retry_total,
)
from example_service.features.notifications.repository import (
    get_notification_delivery_repository,
    get_notification_repository,
)
from example_service.features.notifications.service import get_notification_service
from example_service.infra.database.session import get_async_session
from example_service.infra.email import get_email_service
from example_service.infra.email.schemas import EmailPriority
from example_service.infra.tasks.broker import broker

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
                from example_service.workers.notifications import check_due_reminders
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
                not Reminder.is_completed,
                not Reminder.notification_sent,
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
                results.append(
                    {
                        "to": email_data["to"],
                        "success": result.success,
                        "message_id": result.message_id,
                    },
                )
                if result.success:
                    success_count += 1
                else:
                    failure_count += 1
            except Exception as e:
                results.append(
                    {
                        "to": email_data.get("to"),
                        "success": False,
                        "error": str(e),
                    },
                )
                failure_count += 1

        return {
            "total": len(emails),
            "success_count": success_count,
            "failure_count": failure_count,
            "results": results,
        }

    # ==========================================================================
    # Phase 5: Notification Dispatch Tasks
    # ==========================================================================

    @broker.task(retry_on_error=True, max_retries=3)
    async def dispatch_notification_task(notification_id: str) -> dict:
        """Dispatch notification to all enabled channels.

        This task is queued when a notification is created for immediate delivery.
        It looks up user preferences and dispatches to all enabled channels
        (email, websocket, webhook, in_app).

        Args:
            notification_id: UUID of notification to dispatch.

        Returns:
            Dispatch result with delivery statistics.

        Raises:
            ValueError: If notification not found.
        """
        try:
            uuid_id = UUID(notification_id)
        except ValueError:
            logger.exception(
                "Invalid notification_id format",
                extra={"notification_id": notification_id},
            )
            return {"status": "error", "reason": "invalid_uuid"}

        async with get_async_session() as session:
            repository = get_notification_repository()
            notification = await repository.get(session, uuid_id)

            if not notification:
                logger.error(
                    "Notification not found for dispatch",
                    extra={"notification_id": notification_id},
                )
                return {"status": "error", "reason": "not_found"}

            # Dispatch via service
            service = get_notification_service()
            deliveries = await service.dispatch_notification(session, notification)

            await session.commit()

            logger.info(
                "Notification dispatched successfully",
                extra={
                    "notification_id": notification_id,
                    "deliveries_count": len(deliveries),
                    "channels": [d.channel for d in deliveries],
                },
            )

            return {
                "status": "dispatched",
                "notification_id": notification_id,
                "deliveries_count": len(deliveries),
                "channels": [d.channel for d in deliveries],
                "successful": sum(1 for d in deliveries if d.status == "delivered"),
                "failed": sum(1 for d in deliveries if d.status == "failed"),
                "pending": sum(1 for d in deliveries if d.status == "pending"),
            }

    @broker.task(retry_on_error=True, max_retries=3)
    async def retry_failed_delivery_task(delivery_id: str) -> dict:
        """Retry a failed notification delivery.

        This task is used to retry deliveries that failed previously.
        It implements exponential backoff: 2^attempt * 60s, max 1 hour.

        Args:
            delivery_id: UUID of delivery to retry.

        Returns:
            Retry result with updated status.

        Raises:
            ValueError: If delivery not found or max attempts exceeded.
        """
        try:
            uuid_id = UUID(delivery_id)
        except ValueError:
            logger.exception(
                "Invalid delivery_id format",
                extra={"delivery_id": delivery_id},
            )
            return {"status": "error", "reason": "invalid_uuid"}

        async with get_async_session() as session:
            delivery_repository = get_notification_delivery_repository()
            delivery = await delivery_repository.get(session, uuid_id)

            if not delivery:
                logger.error(
                    "Delivery not found for retry",
                    extra={"delivery_id": delivery_id},
                )
                return {"status": "error", "reason": "not_found"}

            # Check if max attempts reached
            if delivery.attempt_count >= delivery.max_attempts:
                delivery.status = "failed"
                delivery.failed_at = datetime.now(UTC)
                delivery.error_message = "Max retry attempts exceeded"
                await session.commit()

                # Track retry exhaustion
                notification_retry_exhausted_total.labels(
                    channel=delivery.channel,
                ).inc()

                logger.warning(
                    "Delivery retry failed - max attempts exceeded",
                    extra={
                        "delivery_id": delivery_id,
                        "attempts": delivery.attempt_count,
                        "max_attempts": delivery.max_attempts,
                    },
                )

                return {
                    "status": "failed",
                    "reason": "max_attempts_exceeded",
                    "delivery_id": delivery_id,
                    "attempts": delivery.attempt_count,
                }

            # Get notification
            notification_repository = get_notification_repository()
            notification = await notification_repository.get(session, delivery.notification_id)

            if not notification:
                logger.error(
                    "Notification not found for delivery retry",
                    extra={"delivery_id": delivery_id, "notification_id": str(delivery.notification_id)},
                )
                return {"status": "error", "reason": "notification_not_found"}

            # Get appropriate channel dispatcher
            dispatcher = get_notification_dispatcher()
            channel_dispatcher = dispatcher._channels.get(delivery.channel)

            if not channel_dispatcher:
                logger.error(
                    "No dispatcher found for channel",
                    extra={"delivery_id": delivery_id, "channel": delivery.channel},
                )
                delivery.status = "failed"
                delivery.failed_at = datetime.now(UTC)
                delivery.error_message = f"Channel dispatcher not found: {delivery.channel}"
                await session.commit()
                return {"status": "error", "reason": "dispatcher_not_found"}

            # Attempt retry
            logger.info(
                "Retrying notification delivery",
                extra={
                    "delivery_id": delivery_id,
                    "notification_id": str(notification.id),
                    "channel": delivery.channel,
                    "attempt": delivery.attempt_count + 1,
                },
            )

            # Track retry attempt
            notification_retry_total.labels(
                channel=delivery.channel,
            ).inc()

            try:
                result = await channel_dispatcher.send(notification, delivery)

                # Update delivery record
                delivery.attempt_count += 1
                delivery.response_status_code = result.status_code
                delivery.response_body = result.response_body
                delivery.response_time_ms = result.response_time_ms

                if result.success:
                    delivery.status = "delivered"
                    delivery.delivered_at = datetime.now(UTC)
                    delivery.next_retry_at = None

                    logger.info(
                        "Delivery retry succeeded",
                        extra={
                            "delivery_id": delivery_id,
                            "channel": delivery.channel,
                            "attempt": delivery.attempt_count,
                        },
                    )

                    await session.commit()

                    return {
                        "status": "delivered",
                        "delivery_id": delivery_id,
                        "channel": delivery.channel,
                        "attempt": delivery.attempt_count,
                    }
                # Retry failed - update error info
                delivery.error_message = result.error_message
                delivery.error_category = result.error_category

                # Check if should retry again
                if delivery.attempt_count >= delivery.max_attempts:
                    delivery.status = "failed"
                    delivery.failed_at = datetime.now(UTC)
                    delivery.next_retry_at = None
                else:
                    delivery.status = "retrying"
                    # Exponential backoff: 2^attempt * 60s, max 1 hour
                    backoff_seconds = min(2 ** delivery.attempt_count * 60, 3600)
                    delivery.next_retry_at = datetime.now(UTC) + timedelta(seconds=backoff_seconds)

                logger.warning(
                    "Delivery retry failed",
                    extra={
                        "delivery_id": delivery_id,
                        "channel": delivery.channel,
                        "attempt": delivery.attempt_count,
                        "error": result.error_message,
                        "next_retry_at": delivery.next_retry_at.isoformat() if delivery.next_retry_at else None,
                    },
                )

                await session.commit()

                return {
                    "status": delivery.status,
                    "delivery_id": delivery_id,
                    "channel": delivery.channel,
                    "attempt": delivery.attempt_count,
                    "error": result.error_message,
                    "next_retry_at": delivery.next_retry_at.isoformat() if delivery.next_retry_at else None,
                }

            except Exception as exc:
                # Unexpected error
                delivery.attempt_count += 1
                delivery.error_message = str(exc)
                delivery.error_category = "exception"

                if delivery.attempt_count >= delivery.max_attempts:
                    delivery.status = "failed"
                    delivery.failed_at = datetime.now(UTC)
                    delivery.next_retry_at = None
                else:
                    delivery.status = "retrying"
                    backoff_seconds = min(2 ** delivery.attempt_count * 60, 3600)
                    delivery.next_retry_at = datetime.now(UTC) + timedelta(seconds=backoff_seconds)

                await session.commit()

                logger.exception(
                    "Exception during delivery retry",
                    extra={
                        "delivery_id": delivery_id,
                        "channel": delivery.channel,
                        "attempt": delivery.attempt_count,
                    },
                )

                raise

    @broker.task()
    async def process_scheduled_notifications() -> dict:
        """Process notifications scheduled for delivery.

        Scheduled: Every 1 minute (via APScheduler).

        Finds notifications where:
        - status = pending
        - scheduled_for <= now
        - scheduled_for is not None

        Queues dispatch_notification_task for each found notification.

        Returns:
            Processing result with count of scheduled notifications.
        """
        async with get_async_session() as session:
            repository = get_notification_repository()
            notifications = await repository.find_scheduled_pending(session, limit=100)

            if not notifications:
                logger.debug("No scheduled notifications found")
                return {"status": "ok", "processed": 0, "queued_tasks": []}

            logger.info(
                "Found scheduled notifications for processing",
                extra={"count": len(notifications)},
            )

            # Queue dispatch task for each notification
            task_ids = []
            for notification in notifications:
                try:
                    task = await dispatch_notification_task.kiq(
                        notification_id=str(notification.id),
                    )
                    task_ids.append(task.task_id)

                    logger.debug(
                        "Queued dispatch task for scheduled notification",
                        extra={
                            "notification_id": str(notification.id),
                            "task_id": task.task_id,
                            "scheduled_for": notification.scheduled_for.isoformat() if notification.scheduled_for else None,
                        },
                    )
                except Exception:
                    logger.exception(
                        "Failed to queue dispatch task for notification",
                        extra={"notification_id": str(notification.id)},
                    )

            return {
                "status": "ok",
                "processed": len(notifications),
                "queued_tasks": task_ids,
            }

    # ==========================================================================
    # Tenant-Aware Email Tasks (using EnhancedEmailService)
    # ==========================================================================

    @broker.task(retry_on_error=True, max_retries=3)
    async def send_tenant_email_task(
        to: list[str],
        subject: str,
        tenant_id: str | None = None,
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
        """Send an email via background task with tenant-specific configuration.

        This task uses the EnhancedEmailService which supports:
        - Per-tenant email provider configuration
        - Tenant-specific rate limiting
        - Usage logging for billing
        - Audit logging for compliance

        Args:
            to: Recipient email addresses.
            subject: Email subject.
            tenant_id: Tenant ID for per-tenant config (optional).
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
        try:
            from example_service.infra.email.enhanced_service import (
                get_enhanced_email_service,
            )

            email_service = get_enhanced_email_service()
        except RuntimeError:
            # Fall back to basic email service if enhanced service not initialized
            logger.warning(
                "Enhanced email service not initialized, falling back to basic service",
                extra={"tenant_id": tenant_id},
            )
            email_service = get_email_service()  # type: ignore[assignment]
            tenant_id = None  # Basic service doesn't support tenant_id

        # Convert priority string to enum
        priority_enum = EmailPriority(priority)

        # Add tenant_id to metadata for tracking
        email_metadata = metadata or {}
        if tenant_id:
            email_metadata["tenant_id"] = tenant_id
            email_metadata["task_type"] = "tenant_email"

        if hasattr(email_service, "send") and tenant_id is not None:
            # Enhanced service with tenant support
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
                metadata=email_metadata,
                tenant_id=tenant_id,
            )
        else:
            # Basic service
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
                metadata=email_metadata,
            )

        logger.info(
            "Tenant email task completed",
            extra={
                "tenant_id": tenant_id,
                "success": result.success,
                "recipients": len(to),
            },
        )

        return {
            "success": result.success,
            "message_id": result.message_id,
            "status": result.status.value,
            "error": result.error,
            "recipients_accepted": result.recipients_accepted,
            "recipients_rejected": result.recipients_rejected,
            "tenant_id": tenant_id,
        }

    @broker.task(retry_on_error=True, max_retries=3)
    async def send_tenant_template_email_task(
        to: list[str],
        template: str,
        tenant_id: str | None = None,
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
        """Send a template email via background task with tenant-specific configuration.

        This task uses the EnhancedEmailService which supports:
        - Per-tenant email provider configuration
        - Tenant-specific rate limiting
        - Usage logging for billing
        - Audit logging for compliance

        Args:
            to: Recipient email addresses.
            template: Template name (without extension).
            tenant_id: Tenant ID for per-tenant config (optional).
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
        try:
            from example_service.infra.email.enhanced_service import (
                get_enhanced_email_service,
            )

            email_service = get_enhanced_email_service()
            use_enhanced = True
        except RuntimeError:
            # Fall back to basic email service if enhanced service not initialized
            logger.warning(
                "Enhanced email service not initialized, falling back to basic service",
                extra={"tenant_id": tenant_id, "template": template},
            )
            email_service = get_email_service()  # type: ignore[assignment]
            use_enhanced = False

        # Convert priority string to enum
        priority_enum = EmailPriority(priority)

        # Add tenant_id to metadata for tracking
        email_metadata = metadata or {}
        if tenant_id:
            email_metadata["tenant_id"] = tenant_id
            email_metadata["task_type"] = "tenant_template_email"

        try:
            if use_enhanced and tenant_id is not None:
                # Enhanced service with tenant support
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
                    metadata=email_metadata,
                    tenant_id=tenant_id,
                )
            else:
                # Basic service
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
                    metadata=email_metadata,
                )

            logger.info(
                "Tenant template email task completed",
                extra={
                    "tenant_id": tenant_id,
                    "template": template,
                    "success": result.success,
                    "recipients": len(to),
                },
            )

            return {
                "success": result.success,
                "message_id": result.message_id,
                "status": result.status.value,
                "error": result.error,
                "recipients_accepted": result.recipients_accepted,
                "recipients_rejected": result.recipients_rejected,
                "template": template,
                "tenant_id": tenant_id,
            }
        except Exception as e:
            logger.exception(
                "Failed to send tenant template email",
                extra={"tenant_id": tenant_id, "template": template},
            )
            return {
                "success": False,
                "error": str(e),
                "template": template,
                "tenant_id": tenant_id,
            }
