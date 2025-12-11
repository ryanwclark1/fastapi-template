"""Example usage of notification background tasks.

This module demonstrates how to use the Phase 5 background task system
for asynchronous notification processing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def example_immediate_notification(session: AsyncSession, user_id: str) -> None:
    """Example: Create notification with immediate dispatch.

    When scheduled_for=None, the notification is automatically queued
    for background dispatch via dispatch_notification_task.

    Args:
        session: Database session
        user_id: User identifier
    """
    from example_service.features.notifications.service import get_notification_service

    service = get_notification_service()

    # Create notification - will be queued for immediate background dispatch
    notification = await service.create_notification(
        session=session,
        user_id=user_id,
        notification_type="task_assigned",
        title="New Task Assigned",
        body="You have been assigned a new task: Review Q4 Report",
        template_name=None,  # Use provided title/body directly
        priority="high",
        scheduled_for=None,  # Immediate = queues dispatch_notification_task
        source_entity_type="task",
        source_entity_id="task-123",
        actions=[
            {"label": "View Task", "action": "/tasks/task-123", "variant": "primary"},
            {"label": "Dismiss", "action": "dismiss", "variant": "secondary"},
        ],
    )

    await session.commit()

    print(f"✓ Created notification {notification.id}")
    print("✓ Queued dispatch_notification_task for background processing")
    print(f"  Status: {notification.status} (pending)")
    print("  API returns immediately - dispatch happens in background worker")


async def example_scheduled_notification(session: AsyncSession, user_id: str) -> None:
    """Example: Create notification scheduled for future delivery.

    When scheduled_for is set, the notification is NOT dispatched immediately.
    Instead, process_scheduled_notifications (runs every 1 minute) will find
    and queue it when the scheduled time arrives.

    Args:
        session: Database session
        user_id: User identifier
    """
    from example_service.features.notifications.service import get_notification_service

    service = get_notification_service()

    # Schedule notification for 5 minutes from now
    scheduled_time = datetime.now(UTC) + timedelta(minutes=5)

    notification = await service.create_notification(
        session=session,
        user_id=user_id,
        notification_type="reminder",
        title="Meeting Reminder",
        body="Team standup in 5 minutes",
        priority="normal",
        scheduled_for=scheduled_time,  # Future time = not dispatched yet
    )

    await session.commit()

    print(f"✓ Created scheduled notification {notification.id}")
    print(f"  Scheduled for: {scheduled_time.isoformat()}")
    print(f"  Status: {notification.status} (pending)")
    print("  Will be processed by process_scheduled_notifications task")


async def example_template_notification(session: AsyncSession, user_id: str) -> None:
    """Example: Create notification using Jinja2 template.

    Templates are rendered before creating the notification.
    The rendered content is then dispatched via background task.

    Args:
        session: Database session
        user_id: User identifier
    """
    from example_service.features.notifications.service import get_notification_service

    service = get_notification_service()

    # Create notification with template rendering
    notification = await service.create_notification(
        session=session,
        user_id=user_id,
        notification_type="reminder",
        title="Fallback Title",  # Used if template not found
        template_name="reminder_due",  # Template to render
        context={
            "reminder_title": "Review Performance Metrics",
            "reminder_description": "Q4 metrics analysis is due today",
            "due_date": "2025-12-10",
            "priority": "High",
        },
        priority="high",
    )

    await session.commit()

    print(f"✓ Created templated notification {notification.id}")
    print(f"  Template: reminder_due")
    print(f"  Rendered title: {notification.title}")
    print("  Queued for background dispatch")


async def example_manual_retry(session: AsyncSession, delivery_id: str) -> None:
    """Example: Manually retry a failed delivery.

    You can manually trigger retry_failed_delivery_task for any
    failed or pending delivery.

    Args:
        session: Database session
        delivery_id: UUID of delivery to retry
    """
    from example_service.workers.notifications.tasks import retry_failed_delivery_task

    # Queue retry task
    task = await retry_failed_delivery_task.kiq(delivery_id=delivery_id)

    print(f"✓ Queued retry task {task.task_id}")
    print(f"  Delivery ID: {delivery_id}")
    print("  Worker will retry delivery with exponential backoff")

    # Optionally wait for result
    # result = await task.wait_result(timeout=30)
    # print(f"  Result: {result}")


async def example_check_delivery_status(session: AsyncSession, notification_id: str) -> None:
    """Example: Check delivery status for a notification.

    Args:
        session: Database session
        notification_id: UUID of notification
    """
    from uuid import UUID

    from example_service.features.notifications.repository import (
        get_notification_delivery_repository,
        get_notification_repository,
    )

    notification_repo = get_notification_repository()
    delivery_repo = get_notification_delivery_repository()

    # Get notification
    notification = await notification_repo.get(session, UUID(notification_id))

    if not notification:
        print(f"✗ Notification {notification_id} not found")
        return

    print(f"Notification {notification_id}")
    print(f"  Type: {notification.notification_type}")
    print(f"  Status: {notification.status}")
    print(f"  Created: {notification.created_at}")
    print(f"  Dispatched: {notification.dispatched_at}")

    # Get deliveries
    deliveries = await delivery_repo.list_for_notification(session, UUID(notification_id))

    print(f"\n  Deliveries ({len(deliveries)}):")
    for delivery in deliveries:
        print(f"    - Channel: {delivery.channel}")
        print(f"      Status: {delivery.status}")
        print(f"      Attempts: {delivery.attempt_count}/{delivery.max_attempts}")

        if delivery.status in ("pending", "retrying"):
            print(f"      Next retry: {delivery.next_retry_at}")

        if delivery.error_message:
            print(f"      Error: {delivery.error_message}")

        if delivery.status == "delivered":
            print(f"      Delivered: {delivery.delivered_at}")


async def example_bulk_notification(session: AsyncSession, user_ids: list[str]) -> None:
    """Example: Create notifications for multiple users.

    Each notification is queued independently for background dispatch.
    This allows for fast bulk notification creation.

    Args:
        session: Database session
        user_ids: List of user identifiers
    """
    from example_service.features.notifications.service import get_notification_service

    service = get_notification_service()

    print(f"Creating notifications for {len(user_ids)} users...")

    created_count = 0
    for user_id in user_ids:
        try:
            notification = await service.create_notification(
                session=session,
                user_id=user_id,
                notification_type="announcement",
                title="System Maintenance Notice",
                body="The system will be under maintenance on Saturday from 2-4 AM UTC.",
                priority="normal",
            )
            created_count += 1
        except Exception as exc:
            print(f"✗ Failed to create notification for {user_id}: {exc}")

    await session.commit()

    print(f"✓ Created {created_count}/{len(user_ids)} notifications")
    print(f"  Each queued for independent background dispatch")


async def example_with_expiration(session: AsyncSession, user_id: str) -> None:
    """Example: Create notification with expiration.

    Notifications can expire and be cleaned up automatically.

    Args:
        session: Database session
        user_id: User identifier
    """
    from example_service.features.notifications.service import get_notification_service

    service = get_notification_service()

    # Expire in 24 hours
    expires_at = datetime.now(UTC) + timedelta(hours=24)

    notification = await service.create_notification(
        session=session,
        user_id=user_id,
        notification_type="flash_sale",
        title="24-Hour Flash Sale!",
        body="50% off premium features - ends in 24 hours",
        priority="high",
        expires_at=expires_at,
        auto_dismiss=True,
        dismiss_after=5000,  # Auto-dismiss after 5 seconds in UI
    )

    await session.commit()

    print(f"✓ Created expiring notification {notification.id}")
    print(f"  Expires: {expires_at.isoformat()}")
    print(f"  Auto-dismiss: {notification.auto_dismiss} ({notification.dismiss_after}ms)")


# =============================================================================
# Integration Examples
# =============================================================================


async def example_api_endpoint_usage() -> dict:
    """Example: How to use in FastAPI endpoint.

    This shows the typical pattern for creating notifications from API endpoints.

    Returns:
        Response dict
    """
    from example_service.features.notifications.service import get_notification_service
    from example_service.infra.database.session import get_async_session

    async with get_async_session() as session:
        service = get_notification_service()

        notification = await service.create_notification(
            session=session,
            user_id="user-123",
            notification_type="order_shipped",
            title="Order Shipped",
            body="Your order #12345 has been shipped",
            template_name="order_shipped",
            context={
                "order_id": "12345",
                "tracking_number": "1Z999AA10123456784",
                "carrier": "UPS",
            },
            actions=[
                {"label": "Track Order", "action": "/orders/12345/track", "variant": "primary"},
            ],
        )

        await session.commit()

        return {
            "status": "success",
            "notification_id": str(notification.id),
            "message": "Notification queued for delivery",
        }


async def example_event_handler_usage(event_data: dict) -> None:
    """Example: How to use in event handler.

    This shows how to create notifications in response to domain events.

    Args:
        event_data: Event payload
    """
    from example_service.features.notifications.service import get_notification_service
    from example_service.infra.database.session import get_async_session

    async with get_async_session() as session:
        service = get_notification_service()

        # Create notification for file upload event
        await service.create_notification(
            session=session,
            user_id=event_data["user_id"],
            notification_type="file_uploaded",
            title="File Upload Complete",
            body=f"Your file '{event_data['filename']}' has been uploaded successfully",
            priority="normal",
            source_entity_type="file",
            source_entity_id=event_data["file_id"],
            correlation_id=event_data.get("correlation_id"),
        )

        await session.commit()


# =============================================================================
# Monitoring Examples
# =============================================================================


async def example_monitoring_query(session: AsyncSession) -> dict:
    """Example: Query notification statistics.

    Args:
        session: Database session

    Returns:
        Statistics dict
    """
    from example_service.features.notifications.repository import (
        get_notification_delivery_repository,
        get_notification_repository,
    )

    notification_repo = get_notification_repository()
    delivery_repo = get_notification_delivery_repository()

    # Get pending scheduled notifications
    scheduled = await notification_repo.find_scheduled_pending(session, limit=10)

    # Get delivery stats by channel
    email_stats = await delivery_repo.get_stats_by_channel(session, channel="email")
    webhook_stats = await delivery_repo.get_stats_by_channel(session, channel="webhook")

    return {
        "scheduled_count": len(scheduled),
        "next_scheduled": scheduled[0].scheduled_for.isoformat() if scheduled else None,
        "email_deliveries": email_stats,
        "webhook_deliveries": webhook_stats,
    }
