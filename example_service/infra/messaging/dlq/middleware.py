"""DLQ middleware for FastStream integration.

This module provides middleware that wraps FastStream message handlers
to implement retry logic with DLQ routing for failed messages.

The middleware:
1. Extracts retry state from message headers
2. Executes the handler in try/catch
3. On failure:
   a. Checks if exception is retryable
   b. Checks retry limits (count, duration)
   c. Checks poison message detection
   d. If retryable: calculates delay, republishes with updated headers
   e. If not: nacks to route to DLQ

Note: This middleware requires FastStream 0.5+ and RabbitMQ.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from faststream.rabbit import RabbitBroker, RabbitMessage

    from .config import DLQConfig
    from .poison import PoisonMessageDetector

from .calculator import calculate_delay
from .exceptions import is_non_retryable_exception
from .headers import RetryState
from .ttl import is_message_expired

logger = logging.getLogger(__name__)

T = TypeVar("T")


class DLQMiddleware:
    """FastStream middleware for DLQ-based retry with configurable policies.

    This middleware implements the Dead Letter Queue pattern with:
    - Configurable retry policies (IMMEDIATE, LINEAR, EXPONENTIAL, FIBONACCI)
    - Jitter to prevent thundering herd
    - Exception filtering (retryable vs non-retryable)
    - Time-based retry limits
    - Optional poison message detection
    - TTL-based message expiration

    The middleware can be attached to a FastStream broker to automatically
    handle retry logic for all subscribers.

    Example:
        from faststream.rabbit import RabbitBroker
        from example_service.infra.messaging.dlq import DLQConfig, DLQMiddleware

        dlq_config = DLQConfig(
            max_retries=5,
            retry_policy=RetryPolicy.EXPONENTIAL,
        )

        broker = RabbitBroker(...)
        dlq_middleware = DLQMiddleware(broker, dlq_config)

        @broker.subscriber("my.queue")
        async def handle_message(data: dict) -> None:
            # If this raises an exception, DLQMiddleware will handle retry
            process(data)

    Attributes:
        broker: FastStream RabbitBroker instance.
        config: DLQ configuration.
        poison_detector: Optional poison message detector.
    """

    def __init__(
        self,
        broker: RabbitBroker,
        config: DLQConfig,
        poison_detector: PoisonMessageDetector | None = None,
    ) -> None:
        """Initialize DLQ middleware.

        Args:
            broker: FastStream RabbitBroker for republishing.
            config: DLQ configuration with retry settings.
            poison_detector: Optional poison message detector.
        """
        self.broker = broker
        self.config = config
        self.poison_detector = poison_detector

    async def __call__(
        self,
        call_next: Callable[[RabbitMessage], Awaitable[T]],
        msg: RabbitMessage,
    ) -> T:
        """Process message with retry logic.

        This is the main middleware entry point called by FastStream.

        Args:
            call_next: The next handler in the middleware chain.
            msg: The incoming RabbitMQ message.

        Returns:
            Result from the handler if successful.

        Raises:
            Exception: Re-raises after exhausting retries.
        """
        if not self.config.enabled:
            return await call_next(msg)

        # Extract retry state from headers
        headers = dict(msg.headers) if msg.headers else {}
        retry_state = RetryState.from_headers(headers)

        try:
            return await call_next(msg)
        except Exception as exc:
            await self._handle_failure(msg, exc, retry_state)
            raise  # Re-raise after handling

    async def _handle_failure(
        self,
        msg: RabbitMessage,
        exc: Exception,
        retry_state: RetryState,
    ) -> None:
        """Handle message processing failure.

        Implements the retry decision logic:
        1. Check if exception is non-retryable (permanent failure)
        2. Check if max retries exceeded
        3. Check if max duration exceeded
        4. Check for poison message
        5. Check if message expired (TTL)
        6. If all checks pass, schedule retry

        Args:
            msg: The failed message.
            exc: The exception that was raised.
            retry_state: Current retry state from headers.
        """
        exc_name = type(exc).__name__

        # Check 1: Non-retryable exception (permanent failure)
        if is_non_retryable_exception(exc) or not self.config.should_retry_exception(
            exc
        ):
            logger.warning(
                "Non-retryable exception %s, routing to DLQ: %s",
                exc_name,
                str(exc)[:200],
            )
            await self._route_to_dlq(msg, reason=f"non_retryable:{exc_name}")
            return

        # Check 2: Max retries exceeded
        if retry_state.count >= self.config.max_retries:
            logger.error(
                "Max retries (%d) exceeded, routing to DLQ: %s",
                self.config.max_retries,
                str(exc)[:200],
            )
            await self._route_to_dlq(msg, reason="max_retries_exceeded")
            return

        # Check 3: Max duration exceeded
        if self.config.max_retry_duration_ms is not None:
            elapsed = retry_state.elapsed_ms
            if retry_state.first_attempt_ms and elapsed >= self.config.max_retry_duration_ms:
                logger.error(
                    "Max retry duration (%d ms) exceeded, routing to DLQ: %s",
                    self.config.max_retry_duration_ms,
                    str(exc)[:200],
                )
                await self._route_to_dlq(msg, reason="max_duration_exceeded")
                return

        # Check 4: Poison message detection
        if self.poison_detector is not None:
            msg_body = msg.body if hasattr(msg, "body") else b""
            if self.poison_detector.check_and_record(msg_body, exc):
                logger.error(
                    "Poison message detected, routing to DLQ: %s",
                    str(exc)[:200],
                )
                await self._route_to_dlq(msg, reason="poison_message")
                return

        # Check 5: Message TTL expired
        headers = dict(msg.headers) if msg.headers else {}
        if is_message_expired(headers, ttl_ms=self.config.message_ttl_ms):
            logger.warning(
                "Message TTL expired, routing to DLQ: %s",
                str(exc)[:200],
            )
            await self._route_to_dlq(msg, reason="message_expired")
            return

        # All checks passed - schedule retry
        delay_ms = calculate_delay(self.config, retry_state.count)
        new_state = retry_state.increment(delay_ms, exc)

        logger.info(
            "Scheduling retry %d/%d in %d ms for %s: %s",
            new_state.count,
            self.config.max_retries,
            delay_ms,
            exc_name,
            str(exc)[:100],
        )

        # Apply delay
        if delay_ms > 0:
            await asyncio.sleep(delay_ms / 1000.0)

        # Republish with updated headers
        await self._republish_for_retry(msg, new_state)

    async def _republish_for_retry(
        self,
        msg: RabbitMessage,
        retry_state: RetryState,
    ) -> None:
        """Republish message for retry with updated headers.

        Args:
            msg: Original message to republish.
            retry_state: Updated retry state for headers.
        """
        # Merge original headers with retry state
        original_headers = dict(msg.headers) if msg.headers else {}
        retry_headers = retry_state.to_headers()
        new_headers = {**original_headers, **retry_headers}

        # Get routing info from original message
        routing_key = getattr(msg, "routing_key", "") or ""
        exchange = getattr(msg, "exchange", None)
        exchange_name = exchange.name if exchange else ""

        # Republish to same exchange/routing key
        try:
            await self.broker.publish(
                msg.body,
                routing_key=routing_key,
                exchange=exchange_name,
                headers=new_headers,
            )
            # Acknowledge original message after successful republish
            await msg.ack()
        except Exception as pub_exc:
            logger.exception(
                "Failed to republish message for retry: %s",
                str(pub_exc),
            )
            # Nack without requeue to avoid infinite loop
            await msg.nack(requeue=False)

    async def _route_to_dlq(self, msg: RabbitMessage, reason: str) -> None:
        """Route message to Dead Letter Queue.

        Uses RabbitMQ's native DLQ mechanism by nacking without requeue.
        The broker will route to the configured dead-letter exchange.

        Args:
            msg: Message to route to DLQ.
            reason: Reason for DLQ routing (for logging/metrics).
        """
        logger.info("Routing message to DLQ, reason: %s", reason)

        # Add reason to headers before nacking (if possible)
        if self.config.track_failures:
            try:
                # Some message implementations allow header modification
                if hasattr(msg, "headers") and msg.headers is not None:
                    msg.headers["x-dlq-reason"] = reason
            except (AttributeError, TypeError):
                pass  # Headers are immutable, skip

        # Nack without requeue - broker routes to DLX
        await msg.nack(requeue=False)


def create_dlq_middleware(
    broker: RabbitBroker,
    config: DLQConfig | None = None,
    poison_detector: PoisonMessageDetector | None = None,
) -> DLQMiddleware | None:
    """Factory function to create DLQ middleware.

    Returns None if DLQ is disabled in config, allowing conditional
    middleware attachment.

    Args:
        broker: FastStream RabbitBroker.
        config: DLQ configuration (uses defaults if None).
        poison_detector: Optional poison message detector.

    Returns:
        DLQMiddleware instance or None if disabled.

    Example:
        middleware = create_dlq_middleware(broker, config)
        if middleware:
            broker.middlewares.append(middleware)
    """
    if config is None:
        from .config import DLQConfig

        config = DLQConfig()

    if not config.enabled:
        return None

    return DLQMiddleware(broker, config, poison_detector)


__all__ = [
    "DLQMiddleware",
    "create_dlq_middleware",
]
