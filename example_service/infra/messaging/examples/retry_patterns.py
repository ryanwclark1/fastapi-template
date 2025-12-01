"""Retry patterns using utils.retry with FastStream handlers.

This module demonstrates how to use the existing retry utilities from
example_service/utils/retry with FastStream message handlers.

The retry decorator provides:
- Exponential backoff with jitter
- Configurable max attempts and delays
- Exception-based retry decisions
- Retry statistics and metrics
- Integration with existing metrics infrastructure

Reference:
    - Retry utilities: example_service/utils/retry
    - FastStream docs: https://faststream.ag2.ai/latest/getting-started/
"""

from __future__ import annotations

import logging
from typing import Any

from example_service.infra.messaging.broker import router
from example_service.infra.messaging.exchanges import (
    DOMAIN_EVENTS_EXCHANGE,
    EXAMPLE_EVENTS_QUEUE,
)
from example_service.utils.retry import RetryError, retry

if router is None:
    # Skip handler definitions if router not available
    pass
else:
    logger = logging.getLogger(__name__)

    # ──────────────────────────────────────────────────────────────────────────────
    # Basic Retry Pattern
    # ──────────────────────────────────────────────────────────────────────────────

    @router.subscriber(
        EXAMPLE_EVENTS_QUEUE,
        exchange=DOMAIN_EVENTS_EXCHANGE,
    )
    @retry(max_attempts=3, initial_delay=1.0, max_delay=10.0)
    async def handle_with_basic_retry(event: dict[str, Any]) -> None:
        """Handler with basic retry configuration.

        Retries up to 3 times with exponential backoff:
        - Attempt 1: Immediate
        - Attempt 2: ~1 second delay
        - Attempt 3: ~2 seconds delay
        - Max delay capped at 10 seconds

        After max attempts, exception is raised and message goes to DLQ.

        Args:
            event: Event message dictionary.
        """
        logger.info("Processing event with retry", extra={"event_id": event.get("event_id")})

        # Simulate processing that may fail
        # In real code, this would be your business logic
        if event.get("should_fail"):
            raise ConnectionError("Simulated connection failure")

        logger.info("Event processed successfully")

    # ──────────────────────────────────────────────────────────────────────────────
    # Exception-Based Retry Decisions
    # ──────────────────────────────────────────────────────────────────────────────

    @router.subscriber(
        EXAMPLE_EVENTS_QUEUE,
        exchange=DOMAIN_EVENTS_EXCHANGE,
    )
    @retry(
        max_attempts=5,
        initial_delay=0.5,
        max_delay=30.0,
        exceptions=(ConnectionError, TimeoutError, OSError),  # Only retry these
    )
    async def handle_with_exception_filter(event: dict[str, Any]) -> None:
        """Handler that only retries specific exceptions.

        Only ConnectionError, TimeoutError, and OSError trigger retries.
        Other exceptions (ValueError, KeyError, etc.) fail immediately
        and go to DLQ without retries.

        Args:
            event: Event message dictionary.

        Example:
            >>> # ConnectionError -> retries up to 5 times
            >>> # ValueError -> fails immediately, goes to DLQ
        """
        logger.info("Processing event with exception-based retry")

        error_type = event.get("error_type")
        if error_type == "connection":
            raise ConnectionError("Connection failed")
        elif error_type == "validation":
            # This won't be retried (not in exceptions tuple)
            raise ValueError("Validation failed")

        logger.info("Event processed successfully")

    # ──────────────────────────────────────────────────────────────────────────────
    # Retry with Custom Callback
    # ──────────────────────────────────────────────────────────────────────────────

    def on_retry_callback(exception: Exception, attempt: int) -> None:
        """Callback function called on each retry attempt.

        Args:
            exception: Exception that triggered the retry.
            attempt: Retry attempt number (1-based).
        """
        logger.warning(
            f"Retry attempt {attempt}",
            extra={
                "attempt": attempt,
                "exception_type": type(exception).__name__,
                "exception_message": str(exception),
            },
        )
        # TODO: Send metrics, update monitoring, etc.

    @router.subscriber(
        EXAMPLE_EVENTS_QUEUE,
        exchange=DOMAIN_EVENTS_EXCHANGE,
    )
    @retry(
        max_attempts=3,
        initial_delay=1.0,
        max_delay=10.0,
        on_retry=on_retry_callback,
    )
    async def handle_with_retry_callback(event: dict[str, Any]) -> None:
        """Handler with retry callback for monitoring.

        The on_retry callback is called before each retry attempt,
        allowing you to log, send metrics, or perform other actions.

        Args:
            event: Event message dictionary.
        """
        logger.info("Processing event with retry callback")

        # Simulate failure
        if event.get("should_fail"):
            raise ConnectionError("Simulated failure")

        logger.info("Event processed successfully")

    # ──────────────────────────────────────────────────────────────────────────────
    # Retry with Custom Retry Condition
    # ──────────────────────────────────────────────────────────────────────────────

    def should_retry_custom(exception: Exception) -> bool:
        """Custom retry condition function.

        Args:
            exception: Exception to evaluate.

        Returns:
            True if exception should trigger retry, False otherwise.
        """
        # Retry on connection errors
        if isinstance(exception, (ConnectionError, TimeoutError)):
            return True

        # Retry on specific error messages
        error_msg = str(exception).lower()
        if "temporary" in error_msg or "retry" in error_msg:
            return True

        # Don't retry on validation or business logic errors
        return not isinstance(exception, (ValueError, KeyError))

    @router.subscriber(
        EXAMPLE_EVENTS_QUEUE,
        exchange=DOMAIN_EVENTS_EXCHANGE,
    )
    @retry(
        max_attempts=3,
        initial_delay=1.0,
        max_delay=10.0,
        retry_if=should_retry_custom,
    )
    async def handle_with_custom_retry_condition(event: dict[str, Any]) -> None:
        """Handler with custom retry condition.

        Uses retry_if function to determine if exception should be retried.
        More flexible than exceptions tuple for complex retry logic.

        Args:
            event: Event message dictionary.
        """
        logger.info("Processing event with custom retry condition")

        # Business logic here
        if event.get("error") == "temporary":
            raise ConnectionError("Temporary connection issue")  # Will retry
        elif event.get("error") == "permanent":
            raise ValueError("Permanent validation error")  # Won't retry

        logger.info("Event processed successfully")

    # ──────────────────────────────────────────────────────────────────────────────
    # Handling Retry Exhaustion
    # ──────────────────────────────────────────────────────────────────────────────

    @router.subscriber(
        EXAMPLE_EVENTS_QUEUE,
        exchange=DOMAIN_EVENTS_EXCHANGE,
    )
    @retry(max_attempts=3, initial_delay=1.0, max_delay=10.0)
    async def handle_with_retry_exhaustion_handling(event: dict[str, Any]) -> None:
        """Handler that explicitly handles retry exhaustion.

        When all retry attempts are exhausted, RetryError is raised.
        You can catch this to perform cleanup or send alerts before
        the message goes to DLQ.

        Args:
            event: Event message dictionary.

        Note:
            After RetryError is raised, the message will be nack'd and
            routed to DLQ based on queue configuration.
        """
        try:
            logger.info("Processing event")

            # Simulate processing that always fails
            if event.get("should_fail"):
                raise ConnectionError("Persistent connection failure")

            logger.info("Event processed successfully")

        except RetryError as e:
            # All retry attempts exhausted
            logger.error(
                "All retry attempts exhausted",
                extra={
                    "attempts": e.attempts,
                    "last_exception": str(e.last_exception),
                    "statistics": e.statistics.model_dump() if e.statistics else None,
                },
            )

            # TODO: Send alert, update metrics, perform cleanup
            # The message will still go to DLQ after this

            # Re-raise to ensure message goes to DLQ
            raise

    # ──────────────────────────────────────────────────────────────────────────────
    # Retry Statistics and Metrics
    # ──────────────────────────────────────────────────────────────────────────────

    @router.subscriber(
        EXAMPLE_EVENTS_QUEUE,
        exchange=DOMAIN_EVENTS_EXCHANGE,
    )
    @retry(max_attempts=3, initial_delay=1.0, max_delay=10.0)
    async def handle_with_metrics(event: dict[str, Any]) -> None:
        """Handler demonstrating retry metrics integration.

        The retry decorator automatically tracks metrics via:
        - track_retry_attempt: Called on each retry
        - track_retry_exhausted: Called when all retries fail
        - track_retry_success: Called when retry succeeds

        These metrics are available in Prometheus at /metrics.

        Args:
            event: Event message dictionary.
        """
        logger.info("Processing event with metrics tracking")

        # Business logic
        if event.get("should_fail"):
            raise ConnectionError("Simulated failure")

        logger.info("Event processed successfully")

        # Metrics are automatically tracked by the retry decorator
        # Check /metrics endpoint for:
        # - retry_attempt_total
        # - retry_exhausted_total
        # - retry_success_total

    # ──────────────────────────────────────────────────────────────────────────────
    # When to Use Retry vs DLQ
    # ──────────────────────────────────────────────────────────────────────────────

    # Decision Criteria:
    #
    # Use Retry Decorator For:
    # - Transient errors (network issues, timeouts, temporary service unavailability)
    # - Errors that may resolve with time (rate limiting, temporary locks)
    # - Errors where retry makes sense (idempotent operations)
    #
    # Go Directly to DLQ For:
    # - Permanent errors (validation failures, business logic errors)
    # - Errors that won't resolve with retry (authentication failures, permission denied)
    # - Non-idempotent operations that shouldn't be retried
    #
    # Pattern:
    #   1. Use retry decorator for transient errors
    #   2. After max retries, message automatically goes to DLQ
    #   3. DLQ handler processes permanent failures
    #
    # Advanced Considerations (from accent-bus):
    # - Time-based retry limits: Use stop_after_delay parameter to cap total retry time
    # - Jitter: Already included in retry decorator (jitter=True by default) to prevent thundering herd
    # - Exception-based decisions: Use exceptions tuple or retry_if function
    # - Retry statistics: Available via RetryError.statistics for analysis
    # - Custom jitter range: Adjust jitter_range parameter (default: 0.5-1.5 multiplier)

    @router.subscriber(
        EXAMPLE_EVENTS_QUEUE,
        exchange=DOMAIN_EVENTS_EXCHANGE,
    )
    @retry(
        max_attempts=3,
        initial_delay=1.0,
        max_delay=10.0,
        exceptions=(ConnectionError, TimeoutError),  # Only retry transient errors
    )
    async def handle_with_smart_retry(event: dict[str, Any]) -> None:
        """Handler demonstrating smart retry vs DLQ decision.

        This handler:
        1. Retries transient errors (ConnectionError, TimeoutError)
        2. Immediately fails permanent errors (goes to DLQ)
        3. After max retries, goes to DLQ

        Args:
            event: Event message dictionary.
        """
        error_type = event.get("error_type")

        if error_type == "transient":
            # This will be retried
            raise ConnectionError("Transient connection error")
        elif error_type == "permanent":
            # This goes directly to DLQ (not in exceptions tuple)
            raise ValueError("Permanent validation error")
        else:
            # Success
            logger.info("Event processed successfully")
