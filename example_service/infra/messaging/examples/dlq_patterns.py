"""Dead Letter Queue (DLQ) patterns and examples.

This module demonstrates comprehensive DLQ patterns including:
- DLQ message processing and monitoring
- Message inspection and replay
- Alerting on DLQ conditions
- Retry vs DLQ decision criteria
- DLQ message metadata extraction

Reference FastStream documentation:
    https://faststream.ag2.ai/latest/getting-started/
"""

from __future__ import annotations

import logging
from typing import Any

from example_service.infra.messaging.broker import broker

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# DLQ Message Processing
# ──────────────────────────────────────────────────────────────────────────────


def extract_dlq_metadata(message: dict[str, Any]) -> dict[str, Any]:
    """Extract DLQ metadata from message headers.

    DLQ messages include headers with failure information that can be used
    for monitoring, alerting, and debugging.

    Args:
        message: DLQ message dictionary.

    Returns:
        Dictionary with extracted DLQ metadata:
            - original_queue: Original queue name
            - original_routing_key: Original routing key
            - retry_count: Number of retry attempts
            - final_error: Final error message
            - final_error_type: Exception type
            - traceback: Error traceback (if available)

    Example:
        >>> metadata = extract_dlq_metadata(dlq_message)
        >>> print(f"Failed after {metadata['retry_count']} retries")
    """
    headers = message.get("headers", {})
    return {
        "original_queue": headers.get("x-original-queue", "unknown"),
        "original_routing_key": headers.get("x-original-routing-key", "unknown"),
        "retry_count": headers.get("x-retry-count", 0),
        "final_error": headers.get("x-final-error", "unknown"),
        "final_error_type": headers.get("x-final-error-type", "unknown"),
        "traceback": headers.get("x-traceback", ""),
    }


async def process_dlq_message(message: dict[str, Any]) -> None:
    """Process a DLQ message with monitoring and alerting.

    This function demonstrates how to:
    1. Extract DLQ metadata
    2. Log failure information
    3. Send alerts for critical failures
    4. Store failure data for analysis

    Args:
        message: DLQ message dictionary.

    Example:
        >>> @router.subscriber(DLQ_QUEUE, exchange=DLQ_EXCHANGE)
        >>> async def handle_dlq(message: dict):
        ...     await process_dlq_message(message)
    """
    metadata = extract_dlq_metadata(message)

    logger.error(
        "DLQ message received",
        extra={
            "dlq_metadata": metadata,
            "message_body": message,
        },
    )

    # Send alert for high retry count using the alerting system
    if metadata["retry_count"] >= 5:
        logger.critical(
            "High retry count in DLQ",
            extra={
                "retry_count": metadata["retry_count"],
                "original_queue": metadata["original_queue"],
            },
        )
        # Use the DLQ alerter for multi-channel alerting
        from example_service.infra.messaging.dlq.alerting import get_dlq_alerter
        alerter = get_dlq_alerter()
        await alerter.alert_dlq_message(
            original_queue=metadata["original_queue"],
            error_type=metadata["final_error_type"],
            error_message=metadata["final_error"],
            retry_count=metadata["retry_count"],
            message_body=message,
        )

    # Example: Store in database for analysis
    # await store_dlq_message(metadata, message)

    # Example: Check if message should be replayed
    # if should_replay_message(metadata):
    #     await replay_message(message, metadata)


# ──────────────────────────────────────────────────────────────────────────────
# DLQ Monitoring and Alerting
# ──────────────────────────────────────────────────────────────────────────────


class DLQMonitor:
    """Monitor for DLQ conditions and alerting.

    Tracks DLQ message counts and triggers alerts when thresholds are exceeded.
    """

    def __init__(
        self,
        alert_threshold: int = 100,
        critical_threshold: int = 1000,
    ) -> None:
        """Initialize DLQ monitor.

        Args:
            alert_threshold: Warning threshold for message count.
            critical_threshold: Critical threshold for message count.
        """
        self.alert_threshold = alert_threshold
        self.critical_threshold = critical_threshold
        self._message_count = 0

    async def check_dlq_status(self) -> dict[str, Any]:
        """Check DLQ status and return alert level.

        Returns:
            Dictionary with status information:
                - level: Alert level ("ok", "warning", "critical")
                - message_count: Current DLQ message count
                - thresholds: Alert thresholds

        Note:
            In production, you would query RabbitMQ management API
            or use a monitoring tool to get actual queue depth.
        """
        # TODO: Query actual DLQ queue depth from RabbitMQ
        # For now, this is a placeholder
        level = "ok"
        if self._message_count >= self.critical_threshold:
            level = "critical"
        elif self._message_count >= self.alert_threshold:
            level = "warning"

        return {
            "level": level,
            "message_count": self._message_count,
            "thresholds": {
                "warning": self.alert_threshold,
                "critical": self.critical_threshold,
            },
        }


# ──────────────────────────────────────────────────────────────────────────────
# Retry vs DLQ Decision Criteria
# ──────────────────────────────────────────────────────────────────────────────


def should_retry_exception(exception: Exception) -> bool:
    """Determine if an exception should trigger retry logic.

    Transient errors (network issues, timeouts) should be retried.
    Permanent errors (validation failures, business logic errors) should
    go directly to DLQ.

    Args:
        exception: Exception that occurred during processing.

    Returns:
        True if exception should trigger retry, False to go to DLQ.

    Example:
        >>> try:
        ...     process_message(message)
        ... except Exception as e:
        ...     if should_retry_exception(e):
        ...         # Retry logic
        ...     else:
        ...         # Move to DLQ immediately
    """
    # Transient errors - should retry
    transient_errors = (
        ConnectionError,
        TimeoutError,
        OSError,
    )

    # Permanent errors - go to DLQ
    permanent_errors = (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
    )

    if isinstance(exception, transient_errors):
        return True

    if isinstance(exception, permanent_errors):
        return False

    # Default: retry (conservative approach)
    return not isinstance(exception, permanent_errors)


# ──────────────────────────────────────────────────────────────────────────────
# Message Replay Utilities
# ──────────────────────────────────────────────────────────────────────────────


async def replay_dlq_message(
    message: dict[str, Any],
    target_queue: str | None = None,
) -> bool:
    """Replay a DLQ message to its original queue or a target queue.

    This function extracts the original routing information from DLQ headers
    and republishes the message for reprocessing.

    Args:
        message: DLQ message dictionary.
        target_queue: Optional target queue (uses original queue if None).

    Returns:
        True if replay succeeded, False otherwise.

    Example:
        >>> @router.subscriber(DLQ_QUEUE, exchange=DLQ_EXCHANGE)
        >>> async def handle_dlq(message: dict):
        ...     if should_replay(message):
        ...         await replay_dlq_message(message)
    """
    if broker is None:
        logger.warning("Broker not available, cannot replay message")
        return False

    metadata = extract_dlq_metadata(message)
    original_queue = target_queue or metadata["original_queue"]
    original_routing_key = metadata["original_routing_key"]

    if not original_queue or original_queue == "unknown":
        logger.warning("Cannot replay: missing original queue information")
        return False

    try:
        # Remove DLQ-specific headers before replaying
        replay_message = message.copy()
        headers = replay_message.get("headers", {}).copy()
        # Remove DLQ headers
        for key in list(headers.keys()):
            if key.startswith(("x-dlq-", "x-final-", "x-traceback")):
                del headers[key]
        # Reset retry count
        headers["x-retry-count"] = 0
        replay_message["headers"] = headers

        # Republish to original queue
        await broker.publish(
            message=replay_message.get("body", replay_message),
            queue=original_queue,
            routing_key=original_routing_key,
            headers=headers,
        )

        logger.info(
            "DLQ message replayed",
            extra={
                "original_queue": original_queue,
                "original_routing_key": original_routing_key,
            },
        )
        return True

    except Exception as e:
        logger.exception(
            "Failed to replay DLQ message",
            extra={
                "original_queue": original_queue,
                "error": str(e),
            },
        )
        return False


def should_replay_message(metadata: dict[str, Any]) -> bool:
    """Determine if a DLQ message should be replayed.

    Decision criteria:
    - Low retry count suggests transient issue
    - Recent failure suggests issue may be resolved
    - Non-permanent error type

    Args:
        metadata: DLQ metadata dictionary.

    Returns:
        True if message should be replayed, False otherwise.
    """
    retry_count = metadata.get("retry_count", 0)
    error_type = metadata.get("final_error_type", "")

    # Don't replay if too many retries already attempted
    if retry_count >= 5:
        return False

    # Don't replay permanent errors
    permanent_error_types = ("ValueError", "TypeError", "KeyError", "ValidationError")
    if error_type in permanent_error_types:
        return False

    # Replay transient errors with low retry count
    return retry_count < 5 and error_type not in permanent_error_types


# ──────────────────────────────────────────────────────────────────────────────
# DLQ Handler Example
# ──────────────────────────────────────────────────────────────────────────────

if broker is not None:
    # This handler is registered in handlers.py, but here's an example
    # of a more sophisticated DLQ handler with monitoring

    async def advanced_dlq_handler(message: dict[str, Any]) -> None:
        """Advanced DLQ handler with monitoring and alerting.

        This demonstrates a production-ready DLQ handler that:
        1. Extracts metadata
        2. Logs with structured data
        3. Checks replay eligibility
        4. Sends alerts for critical failures
        5. Updates monitoring metrics

        Args:
            message: DLQ message dictionary.
        """
        metadata = extract_dlq_metadata(message)

        # Log with structured data
        logger.error(
            "DLQ message processing",
            extra={
                "dlq_metadata": metadata,
                "original_queue": metadata["original_queue"],
                "retry_count": metadata["retry_count"],
                "error_type": metadata["final_error_type"],
            },
        )

        # Check if should replay
        if should_replay_message(metadata):
            logger.info(
                "Attempting to replay DLQ message",
                extra={"original_queue": metadata["original_queue"]},
            )
            success = await replay_dlq_message(message)
            if success:
                logger.info("DLQ message replayed successfully")
            else:
                logger.warning("DLQ message replay failed")
        else:
            logger.warning(
                "DLQ message not eligible for replay",
                extra={
                    "retry_count": metadata["retry_count"],
                    "error_type": metadata["final_error_type"],
                },
            )

        # Send alerts for critical conditions
        if metadata["retry_count"] >= 5:
            logger.critical(
                "Critical DLQ condition: high retry count",
                extra={"retry_count": metadata["retry_count"]},
            )
            # Send alert via configured channels (email, Slack, webhook)
            from example_service.infra.messaging.dlq.alerting import get_dlq_alerter
            alerter = get_dlq_alerter()
            await alerter.alert_dlq_message(
                original_queue=metadata["original_queue"],
                error_type=metadata["final_error_type"],
                error_message=metadata["final_error"],
                retry_count=metadata["retry_count"],
            )
