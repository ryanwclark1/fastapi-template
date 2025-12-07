"""Background outbox processor for reliable event publishing.

The processor runs as a background task that:
1. Polls the outbox table for pending events
2. Publishes events to RabbitMQ
3. Marks events as processed or schedules retries on failure

The processor uses:
- Batch processing for efficiency
- FOR UPDATE SKIP LOCKED for concurrent processing
- Exponential backoff for failed events
- Graceful shutdown handling
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import TYPE_CHECKING, Any

from example_service.core.settings import get_rabbit_settings

if TYPE_CHECKING:
    from faststream.rabbit import RabbitBroker

logger = logging.getLogger(__name__)

# Global processor instance
_processor: OutboxProcessor | None = None


class OutboxProcessor:
    """Background processor for publishing outbox events.

    Polls the outbox table and publishes events to RabbitMQ.
    Handles failures with exponential backoff retries.

    Attributes:
        batch_size: Number of events to process per batch
        poll_interval: Seconds between polling cycles
        max_retries: Maximum retry attempts before giving up
    """

    def __init__(
        self,
        *,
        batch_size: int = 100,
        poll_interval: float = 5.0,
        max_retries: int = 5,
        queue_name: str = "domain-events",
    ) -> None:
        """Initialize the outbox processor.

        Args:
            batch_size: Events to fetch per batch
            poll_interval: Seconds between polls when idle
            max_retries: Max retries before marking as dead letter
            queue_name: RabbitMQ queue for publishing events
        """
        self.batch_size = batch_size
        self.poll_interval = poll_interval
        self.max_retries = max_retries
        self.queue_name = queue_name

        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._broker: RabbitBroker | None = None

    async def start(self) -> None:
        """Start the background processor.

        Begins polling the outbox table and publishing events.
        """
        if self._running:
            logger.warning("Outbox processor already running")
            return

        # Get broker instance
        from example_service.infra.messaging.broker import broker

        self._broker = broker

        if self._broker is None:
            logger.warning("RabbitMQ broker not configured, outbox processor disabled")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "Outbox processor started",
            extra={
                "batch_size": self.batch_size,
                "poll_interval": self.poll_interval,
                "max_retries": self.max_retries,
            },
        )

    async def stop(self) -> None:
        """Stop the background processor gracefully.

        Waits for the current batch to complete before stopping.
        """
        if not self._running:
            return

        self._running = False

        if self._task:
            # Wait for task to complete current batch
            try:
                await asyncio.wait_for(self._task, timeout=30.0)
            except TimeoutError:
                logger.warning("Outbox processor shutdown timed out, cancelling")
                self._task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._task
            self._task = None

        logger.info("Outbox processor stopped")

    async def _run_loop(self) -> None:
        """Main processing loop."""
        while self._running:
            try:
                processed = await self._process_batch()

                if processed == 0:
                    # No events, wait before polling again
                    await asyncio.sleep(self.poll_interval)
                else:
                    # More events might be available, continue immediately
                    # but yield to other tasks
                    await asyncio.sleep(0)

            except asyncio.CancelledError:
                logger.info("Outbox processor loop cancelled")
                break
            except Exception:
                logger.exception("Error in outbox processor loop")
                # Back off on errors to avoid tight error loop
                await asyncio.sleep(self.poll_interval * 2)

    async def _process_batch(self) -> int:
        """Process a batch of pending events.

        Returns:
            Number of events processed in this batch
        """
        from example_service.infra.database.session import get_async_session
        from example_service.infra.events.outbox.repository import OutboxRepository

        repo = OutboxRepository()
        processed_count = 0

        async with get_async_session() as session:
            # Fetch pending events with row locking
            events = await repo.fetch_pending(
                session,
                batch_size=self.batch_size,
                max_retries=self.max_retries,
            )

            if not events:
                return 0

            logger.debug(
                "Processing outbox batch",
                extra={"batch_size": len(events)},
            )

            for event in events:
                try:
                    await self._publish_event(event)
                    await repo.mark_processed(session, str(event.id))
                    processed_count += 1

                    logger.debug(
                        "Event published successfully",
                        extra={
                            "event_id": str(event.id),
                            "event_type": event.event_type,
                        },
                    )

                except Exception as e:
                    error_msg = str(e)
                    await repo.mark_failed(session, str(event.id), error_msg)

                    logger.warning(
                        "Failed to publish event, scheduled for retry",
                        extra={
                            "event_id": str(event.id),
                            "event_type": event.event_type,
                            "error": error_msg,
                            "retry_count": event.retry_count + 1,
                        },
                    )

            # Commit all changes
            await session.commit()

        if processed_count > 0:
            logger.info(
                "Outbox batch processed",
                extra={"processed": processed_count, "total": len(events)},
            )

        return processed_count

    async def _publish_event(self, event: Any) -> None:
        """Publish a single event to RabbitMQ.

        Args:
            event: EventOutbox instance to publish

        Raises:
            Exception: If publishing fails
        """
        if self._broker is None:
            msg = "Broker not initialized"
            raise RuntimeError(msg)

        # Parse the payload
        payload = json.loads(event.payload)

        # Add routing metadata
        message = {
            "event_type": event.event_type,
            "event_version": event.event_version,
            "correlation_id": event.correlation_id,
            "aggregate_type": event.aggregate_type,
            "aggregate_id": event.aggregate_id,
            "data": payload,
        }

        # Publish to RabbitMQ
        await self._broker.publish(
            message=message,
            queue=self.queue_name,
            correlation_id=event.correlation_id,
        )

    async def process_one(self) -> bool:
        """Process a single pending event (for testing).

        Returns:
            True if an event was processed, False if none pending
        """
        from example_service.infra.database.session import get_async_session
        from example_service.infra.events.outbox.repository import OutboxRepository

        repo = OutboxRepository()

        async with get_async_session() as session:
            events = await repo.fetch_pending(session, batch_size=1, max_retries=self.max_retries)

            if not events:
                return False

            event = events[0]

            try:
                await self._publish_event(event)
                await repo.mark_processed(session, str(event.id))
                await session.commit()
                return True

            except Exception as e:
                await repo.mark_failed(session, str(event.id), str(e))
                await session.commit()
                raise


async def start_outbox_processor(
    *,
    batch_size: int = 100,
    poll_interval: float = 5.0,
    max_retries: int = 5,
) -> None:
    """Start the global outbox processor.

    Args:
        batch_size: Events to process per batch
        poll_interval: Seconds between polling cycles
        max_retries: Maximum retry attempts
    """
    global _processor

    rabbit_settings = get_rabbit_settings()
    if not rabbit_settings.is_configured:
        logger.info("RabbitMQ not configured, skipping outbox processor")
        return

    _processor = OutboxProcessor(
        batch_size=batch_size,
        poll_interval=poll_interval,
        max_retries=max_retries,
    )
    await _processor.start()


async def stop_outbox_processor() -> None:
    """Stop the global outbox processor."""
    global _processor

    if _processor is not None:
        await _processor.stop()
        _processor = None


def get_outbox_processor() -> OutboxProcessor | None:
    """Get the global outbox processor instance."""
    return _processor


__all__ = [
    "OutboxProcessor",
    "get_outbox_processor",
    "start_outbox_processor",
    "stop_outbox_processor",
]
