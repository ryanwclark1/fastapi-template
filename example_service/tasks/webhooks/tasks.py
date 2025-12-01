"""Webhook delivery task definitions.

This module provides:
- Asynchronous webhook delivery via HTTP POST
- Exponential backoff retry strategy
- Automatic retry processing for failed deliveries
- Status tracking and response logging
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from example_service.features.webhooks.client import WebhookClient
from example_service.features.webhooks.repository import (
    get_webhook_delivery_repository,
    get_webhook_repository,
)
from example_service.features.webhooks.schemas import DeliveryStatus
from example_service.infra.database.session import get_async_session
from example_service.tasks.broker import broker

logger = logging.getLogger(__name__)


class WebhookDeliveryError(Exception):
    """Webhook delivery operation error."""

    pass


# Retry configuration
MAX_RETRIES = 6  # Total of 7 attempts (initial + 6 retries)
BACKOFF_BASE = 60  # Start with 1 minute
MAX_BACKOFF = 3600  # Cap at 1 hour


def calculate_backoff(attempt_count: int) -> int:
    """Calculate exponential backoff in seconds.

    Strategy: 1min, 2min, 4min, 8min, 16min, 32min, capped at 1 hour.

    Args:
        attempt_count: Number of previous attempts (0-indexed).

    Returns:
        Seconds to wait before next retry.
    """
    backoff = BACKOFF_BASE * (2**attempt_count)
    return int(min(backoff, MAX_BACKOFF))


async def get_webhook_delivery(delivery_id: str) -> dict[str, Any] | None:
    """Retrieve webhook delivery record from database.

    Args:
        delivery_id: Unique delivery identifier.

    Returns:
        Dictionary containing delivery metadata, or None if not found.
    """
    async with get_async_session() as session:
        delivery_repo = get_webhook_delivery_repository()
        delivery = await delivery_repo.get(session, UUID(delivery_id))

        if not delivery:
            return None

        # Get associated webhook for URL and secret
        webhook_repo = get_webhook_repository()
        webhook = await webhook_repo.get(session, delivery.webhook_id)

        if not webhook:
            logger.error(
                "Webhook configuration not found for delivery",
                extra={
                    "delivery_id": delivery_id,
                    "webhook_id": str(delivery.webhook_id),
                },
            )
            return None

        return {
            "id": str(delivery.id),
            "webhook_id": str(delivery.webhook_id),
            "webhook": webhook,  # Pass entire webhook object for client
            "url": webhook.url,
            "secret": webhook.secret,
            "event_type": delivery.event_type,
            "event_id": delivery.event_id,
            "payload": delivery.payload,
            "attempt_count": delivery.attempt_count,
            "max_attempts": delivery.max_attempts,
            "status": delivery.status,
            "custom_headers": webhook.custom_headers,
            "timeout": webhook.timeout_seconds,
        }


async def update_delivery_status(
    delivery_id: str,
    status: str,
    response_status_code: int | None = None,
    response_body: str | None = None,
    response_time_ms: int | None = None,
    error_message: str | None = None,
    next_retry_at: datetime | None = None,
) -> None:
    """Update webhook delivery status in database.

    Args:
        delivery_id: Unique delivery identifier.
        status: New status (delivered, retrying, failed).
        response_status_code: HTTP response status code.
        response_body: HTTP response body.
        response_time_ms: Response time in milliseconds.
        error_message: Error message if delivery failed.
        next_retry_at: Timestamp for next retry attempt.
    """
    async with get_async_session() as session:
        repo = get_webhook_delivery_repository()
        await repo.update_status(
            session,
            UUID(delivery_id),
            status,
            response_status_code=response_status_code,
            response_body=response_body,
            response_time_ms=response_time_ms,
            error_message=error_message,
            next_retry_at=next_retry_at,
        )
        await session.commit()

    logger.info(
        "Delivery status updated",
        extra={
            "delivery_id": delivery_id,
            "status": status,
            "response_status_code": response_status_code,
            "error_message": error_message,
            "next_retry_at": next_retry_at.isoformat() if next_retry_at else None,
        },
    )


async def find_deliveries_for_retry() -> list[dict[str, Any]]:
    """Find webhook deliveries that are due for retry.

    Returns:
        List of delivery dictionaries ready for retry.
    """
    async with get_async_session() as session:
        repo = get_webhook_delivery_repository()
        deliveries = await repo.find_retries_due(session)

        return [
            {
                "id": str(delivery.id),
                "attempt_count": delivery.attempt_count,
                "next_retry_at": delivery.next_retry_at,
            }
            for delivery in deliveries
        ]


if broker is not None:

    @broker.task(retry_on_error=True, max_retries=2)
    async def deliver_webhook(delivery_id: str) -> dict[str, Any]:
        """Deliver webhook via HTTP POST with retry logic.

        Implements exponential backoff retry strategy:
        - Attempt 0: Immediate
        - Attempt 1: 1 minute
        - Attempt 2: 2 minutes
        - Attempt 3: 4 minutes
        - Attempt 4: 8 minutes
        - Attempt 5: 16 minutes
        - Attempt 6: 32 minutes

        On success: Updates status to 'delivered' and records response.
        On failure: Increments attempt count, calculates next retry time,
                    updates status to 'retrying' or 'failed' if max retries exceeded.

        Args:
            delivery_id: Unique identifier of the webhook delivery.

        Returns:
            Delivery result dictionary.

        Raises:
            WebhookDeliveryError: If delivery fails after all retries.

        Example:
                    # Schedule webhook delivery
            from example_service.tasks.webhooks import deliver_webhook
            task = await deliver_webhook.kiq(delivery_id="delivery_123")
            result = await task.wait_result()
        """
        logger.info(
            "Delivering webhook",
            extra={"delivery_id": delivery_id},
        )

        try:
            # Step 1: Retrieve delivery record
            delivery = await get_webhook_delivery(delivery_id)

            if not delivery:
                logger.error(
                    "Webhook delivery not found",
                    extra={"delivery_id": delivery_id},
                )
                raise WebhookDeliveryError(f"Delivery not found: {delivery_id}")

            # Step 2: Check if max retries exceeded
            if delivery["attempt_count"] >= delivery["max_attempts"]:
                logger.warning(
                    "Max retries exceeded for webhook delivery",
                    extra={
                        "delivery_id": delivery_id,
                        "attempt_count": delivery["attempt_count"],
                        "max_attempts": delivery["max_attempts"],
                    },
                )
                await update_delivery_status(
                    delivery_id,
                    status=DeliveryStatus.FAILED.value,
                    error_message="Max retries exceeded",
                )
                return {
                    "status": "failed",
                    "delivery_id": delivery_id,
                    "reason": "max_retries_exceeded",
                    "attempt_count": delivery["attempt_count"],
                }

            logger.info(
                "Attempting webhook delivery",
                extra={
                    "delivery_id": delivery_id,
                    "attempt": delivery["attempt_count"] + 1,
                    "url": delivery["url"],
                    "event_type": delivery["event_type"],
                },
            )

            # Step 3: Send webhook request using WebhookClient
            try:
                client = WebhookClient(timeout_seconds=delivery["timeout"])
                result = await client.deliver(
                    webhook=delivery["webhook"],
                    event_type=delivery["event_type"],
                    event_id=delivery["event_id"],
                    payload=delivery["payload"],
                )

                # Step 4: Check if successful
                if result.success:
                    # Success: Update status to delivered
                    await update_delivery_status(
                        delivery_id,
                        status=DeliveryStatus.DELIVERED.value,
                        response_status_code=result.status_code,
                        response_body=result.response_body,
                        response_time_ms=result.response_time_ms,
                    )

                    response_data = {
                        "status": "delivered",
                        "delivery_id": delivery_id,
                        "attempt_count": delivery["attempt_count"] + 1,
                        "response_status_code": result.status_code,
                        "response_time_ms": result.response_time_ms,
                        "url": delivery["url"],
                    }

                    logger.info(
                        "Webhook delivered successfully",
                        extra=response_data,
                    )

                    return response_data

                else:
                    # Non-2xx response or error: Schedule retry
                    raise WebhookDeliveryError(result.error_message or f"HTTP {result.status_code}")

            except Exception as e:
                # Step 5: Handle delivery failure
                new_attempt_count = delivery["attempt_count"] + 1

                logger.warning(
                    "Webhook delivery attempt failed",
                    extra={
                        "delivery_id": delivery_id,
                        "attempt": new_attempt_count,
                        "error": str(e),
                    },
                )

                # Calculate next retry time
                if new_attempt_count < delivery["max_attempts"]:
                    backoff_seconds = calculate_backoff(new_attempt_count - 1)
                    next_retry_at = datetime.now(UTC) + timedelta(seconds=backoff_seconds)

                    await update_delivery_status(
                        delivery_id,
                        status=DeliveryStatus.RETRYING.value,
                        error_message=str(e),
                        next_retry_at=next_retry_at,
                    )

                    logger.info(
                        "Webhook delivery will retry",
                        extra={
                            "delivery_id": delivery_id,
                            "attempt": new_attempt_count,
                            "next_retry_at": next_retry_at.isoformat(),
                            "backoff_seconds": backoff_seconds,
                        },
                    )

                    return {
                        "status": "retrying",
                        "delivery_id": delivery_id,
                        "attempt_count": new_attempt_count,
                        "next_retry_at": next_retry_at.isoformat(),
                        "error": str(e),
                    }
                else:
                    # Max retries exceeded
                    await update_delivery_status(
                        delivery_id,
                        status=DeliveryStatus.FAILED.value,
                        error_message=str(e),
                    )

                    logger.error(
                        "Webhook delivery failed permanently",
                        extra={
                            "delivery_id": delivery_id,
                            "attempt_count": new_attempt_count,
                            "error": str(e),
                        },
                    )

                    return {
                        "status": "failed",
                        "delivery_id": delivery_id,
                        "attempt_count": new_attempt_count,
                        "error": str(e),
                    }

        except Exception as e:
            logger.exception(
                "Webhook delivery task failed",
                extra={"delivery_id": delivery_id, "error": str(e)},
            )
            raise WebhookDeliveryError(f"Failed to deliver webhook {delivery_id}: {e}") from e

    @broker.task()
    async def process_webhook_retries() -> dict[str, Any]:
        """Process webhook deliveries that are due for retry.

        Scheduled: Every 1 minute (can be configured via scheduler).

        Finds all webhook deliveries with status='retrying' where next_retry_at
        is in the past, and re-queues them for delivery.

        Returns:
            Retry processing result dictionary.

        Example:
                    # Manually trigger retry processing
            from example_service.tasks.webhooks import process_webhook_retries
            task = await process_webhook_retries.kiq()
            result = await task.wait_result()
        """
        logger.info("Processing webhook retries")

        try:
            # Step 1: Find deliveries due for retry
            deliveries = await find_deliveries_for_retry()

            if not deliveries:
                logger.debug("No webhook deliveries due for retry")
                return {
                    "status": "success",
                    "queued_count": 0,
                }

            logger.info(
                "Found deliveries due for retry",
                extra={"count": len(deliveries)},
            )

            # Step 2: Re-queue deliveries
            queued_count = 0
            failed_count = 0

            for delivery in deliveries:
                try:
                    # Queue the delivery task
                    await deliver_webhook.kiq(delivery_id=delivery["id"])
                    queued_count += 1

                    logger.debug(
                        "Webhook delivery re-queued",
                        extra={
                            "delivery_id": delivery["id"],
                            "attempt_count": delivery["attempt_count"],
                            "next_retry_at": delivery["next_retry_at"],
                        },
                    )

                except Exception as e:
                    failed_count += 1
                    logger.warning(
                        "Failed to re-queue webhook delivery",
                        extra={
                            "delivery_id": delivery["id"],
                            "error": str(e),
                        },
                    )

            result = {
                "status": "success",
                "queued_count": queued_count,
                "failed_count": failed_count,
                "total_found": len(deliveries),
            }

            logger.info(
                "Webhook retry processing completed",
                extra=result,
            )

            return result

        except Exception as e:
            logger.exception(
                "Webhook retry processing failed",
                extra={"error": str(e)},
            )
            raise
