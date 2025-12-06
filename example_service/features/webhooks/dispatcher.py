"""Event dispatcher for webhooks.

This module provides utilities for dispatching events to subscribed webhooks.
In a production environment, this would typically queue delivery tasks to a
background job system (Celery, RQ, etc.) rather than executing synchronously.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
from typing import TYPE_CHECKING

from example_service.features.webhooks.client import WebhookClient
from example_service.features.webhooks.models import WebhookDelivery
from example_service.features.webhooks.repository import (
    get_webhook_delivery_repository,
    get_webhook_repository,
)
from example_service.features.webhooks.schemas import DeliveryStatus
from example_service.infra.logging import get_lazy_logger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
lazy_logger = get_lazy_logger(__name__)


async def dispatch_event(
    session: AsyncSession,
    event_type: str,
    event_id: str,
    payload: dict,
) -> int:
    """Dispatch an event to all subscribed webhooks.

    Finds all active webhooks subscribed to the event type and creates
    delivery records for each. In a production system, this would queue
    background tasks rather than executing deliveries synchronously.

    Args:
        session: Database session
        event_type: Type of event (e.g., "user.created", "order.completed")
        event_id: Unique identifier for this event occurrence
        payload: Event payload data

    Returns:
        Number of delivery records created
    """
    webhook_repo = get_webhook_repository()
    delivery_repo = get_webhook_delivery_repository()

    # Find all active webhooks subscribed to this event type
    webhooks = await webhook_repo.find_by_event_type(
        session,
        event_type,
        active_only=True,
    )

    if not webhooks:
        lazy_logger.debug(
            lambda: f"dispatcher.dispatch_event: event_type={event_type!r}, event_id={event_id!r} -> no subscribed webhooks"
        )
        return 0

    # Create delivery records for each webhook
    deliveries = []
    for webhook in webhooks:
        delivery = WebhookDelivery(
            webhook_id=webhook.id,
            event_type=event_type,
            event_id=event_id,
            payload=payload,
            status=DeliveryStatus.PENDING.value,
            attempt_count=0,
            max_attempts=webhook.max_retries,
            next_retry_at=datetime.now(UTC),  # Schedule immediate delivery
        )
        deliveries.append(delivery)

    # Bulk insert deliveries
    created = await delivery_repo.create_many(session, deliveries)
    await session.commit()

    # INFO level - business event (webhook dispatch)
    logger.info(
        "Event dispatched to webhooks",
        extra={
            "event_type": event_type,
            "event_id": event_id,
            "webhook_count": len(webhooks),
            "delivery_count": len(created),
            "operation": "dispatcher.dispatch_event",
        },
    )

    # Note: In production, you would queue background tasks here
    # Example with Celery:
    # for delivery in created:
    #     deliver_webhook_task.delay(delivery.id)

    return len(created)


async def process_pending_deliveries(
    session: AsyncSession,
    *,
    limit: int = 100,
) -> int:
    """Process pending webhook deliveries.

    This function should be called by a background worker to process
    queued webhook deliveries. It finds deliveries that are due for
    delivery/retry and attempts to send them.

    Args:
        session: Database session
        limit: Maximum number of deliveries to process

    Returns:
        Number of deliveries processed
    """
    delivery_repo = get_webhook_delivery_repository()
    webhook_repo = get_webhook_repository()
    client = WebhookClient()

    # Find deliveries due for retry
    deliveries = await delivery_repo.find_retries_due(session)

    # Limit to prevent overwhelming the system
    deliveries = deliveries[:limit]

    processed_count = 0

    for delivery in deliveries:
        # Load webhook configuration
        webhook = await webhook_repo.get(session, delivery.webhook_id)
        if webhook is None or not webhook.is_active:
            # Webhook was deleted or deactivated
            await delivery_repo.update_status(
                session,
                delivery.id,
                DeliveryStatus.FAILED.value,
                error_message="Webhook not found or inactive",
            )
            await session.commit()
            continue

        # Attempt delivery
        result = await client.deliver(
            webhook=webhook,
            event_type=delivery.event_type,
            event_id=delivery.event_id,
            payload=delivery.payload,
        )

        # Update delivery status based on result
        if result.success:
            await delivery_repo.update_status(
                session,
                delivery.id,
                DeliveryStatus.DELIVERED.value,
                response_status_code=result.status_code,
                response_body=result.response_body,
                response_time_ms=result.response_time_ms,
            )
        # Check if we should retry
        elif delivery.attempt_count + 1 < delivery.max_attempts:
            # Calculate exponential backoff
            retry_delay_seconds = min(2**delivery.attempt_count * 60, 3600)  # Max 1 hour
            next_retry_at = datetime.now(UTC) + timedelta(seconds=retry_delay_seconds)

            await delivery_repo.update_status(
                session,
                delivery.id,
                DeliveryStatus.RETRYING.value,
                response_status_code=result.status_code,
                response_body=result.response_body,
                response_time_ms=result.response_time_ms,
                error_message=result.error_message,
                next_retry_at=next_retry_at,
            )
        else:
            # Max retries reached
            await delivery_repo.update_status(
                session,
                delivery.id,
                DeliveryStatus.FAILED.value,
                response_status_code=result.status_code,
                response_body=result.response_body,
                response_time_ms=result.response_time_ms,
                error_message=result.error_message,
            )

        await session.commit()
        processed_count += 1

    if processed_count > 0:
        logger.info(
            "Processed pending webhook deliveries",
            extra={
                "processed_count": processed_count,
                "operation": "dispatcher.process_pending_deliveries",
            },
        )
    else:
        lazy_logger.debug(lambda: "dispatcher.process_pending_deliveries: no deliveries to process")

    return processed_count


__all__ = ["dispatch_event", "process_pending_deliveries"]
