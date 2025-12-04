"""Scheduled message publishing with taskiq-faststream.

This module demonstrates how to use taskiq-faststream to publish messages
on a schedule (like cron jobs). The messages are published to FastStream
queues and consumed by FastStream handlers.

How it works:
1. BrokerWrapper wraps the FastStream broker
2. .task() defines what message to publish and when
3. Run `taskiq scheduler example_service.infra.tasks.broker:stream_scheduler`
4. The scheduler publishes messages at the specified times
5. FastStream handlers in handlers.py consume the messages

This is useful for:
- Periodic health checks / heartbeats
- Scheduled data syncs
- Timed notifications
- Regular cleanup triggers

Run the scheduler:
    taskiq scheduler example_service.infra.tasks.broker:stream_scheduler
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from example_service.core.settings import get_rabbit_settings
from example_service.infra.tasks.broker import stream_broker

logger = logging.getLogger(__name__)

# Get settings
rabbit_settings = get_rabbit_settings()

# Define scheduled message publishing tasks
# These are NOT background tasks - they publish messages on a schedule

if stream_broker is not None and rabbit_settings.is_configured:
    # Define the queue name
    ECHO_SERVICE_QUEUE = rabbit_settings.get_prefixed_queue("echo-service")

    # Define a callback function that generates the message to publish
    async def generate_heartbeat_message() -> dict:
        """Generate a heartbeat message to publish.

        This function is called by the scheduler at each scheduled time.
        The returned value is published to the specified queue.
        """
        return {
            "event_type": "scheduled_heartbeat",
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "example-service",
            "source": "taskiq-scheduler",
        }

    # Schedule heartbeat message every minute
    # This publishes to the echo-service queue, which will be consumed
    # by the echo handler in handlers.py
    stream_broker.task(
        message=generate_heartbeat_message,
        queue=ECHO_SERVICE_QUEUE,
        schedule=[{"cron": "* * * * *"}],  # Every minute
    )

    logger.info(
        "Scheduled heartbeat message configured",
        extra={"queue": ECHO_SERVICE_QUEUE, "schedule": "every minute"},
    )

    # Example: Multiple messages per task execution using a generator
    async def generate_batch_messages() -> Any:
        """Generate multiple messages in a single task execution.

        Using a generator allows publishing multiple messages per schedule tick.
        """
        for i in range(3):
            yield {
                "event_type": "batch_message",
                "batch_id": i,
                "timestamp": datetime.now(UTC).isoformat(),
            }

    # Uncomment to enable batch message publishing every 5 minutes
    # stream_broker.task(
    #     message=generate_batch_messages,
    #     queue=ECHO_SERVICE_QUEUE,
    #     schedule=[{"cron": "*/5 * * * *"}],  # Every 5 minutes
    # )

    # Example: Static message (no callback)
    # stream_broker.task(
    #     message={"event_type": "ping", "source": "scheduler"},
    #     queue=ECHO_SERVICE_QUEUE,
    #     schedule=[{"cron": "0 * * * *"}],  # Every hour on the hour
    # )

else:
    logger.debug("Scheduled message publishing not configured")
