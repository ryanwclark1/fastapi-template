"""Subscription resolvers for real-time GraphQL updates.

Provides WebSocket subscriptions for:
- reminderEvents: Subscribe to all reminder events (created, updated, completed, deleted)
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Annotated

import strawberry

from example_service.features.graphql.types.reminders import (
    ReminderEvent,
    ReminderEventType,
    ReminderType,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from strawberry.types import Info

    from example_service.features.graphql.context import GraphQLContext

logger = logging.getLogger(__name__)

# Type alias for event types filter argument
EventTypesArg = Annotated[
    list[str] | None,
    strawberry.argument(description="Filter by event types (CREATED, UPDATED, COMPLETED, DELETED)"),
]


async def _subscribe_to_channel(
    channel: str,
    event_types: list[str] | None = None,
) -> AsyncGenerator[dict]:
    """Subscribe to Redis PubSub channel for reminder events.

    Creates a dedicated Redis connection for the subscription
    (PubSub blocks, so we cannot use pooled connections).

    Args:
        channel: Redis channel to subscribe to
        event_types: Optional filter for event types

    Yields:
        Parsed event data dictionaries
    """
    from example_service.core.settings import get_redis_settings

    redis_settings = get_redis_settings()
    if not redis_settings.is_configured:
        logger.warning("Redis not configured, subscriptions unavailable")
        return

    # Import here to avoid import errors if redis not installed
    from redis.asyncio import Redis

    # Create dedicated connection for subscription
    redis = Redis.from_url(
        str(redis_settings.url),
        decode_responses=True,
    )

    try:
        pubsub = redis.pubsub()
        await pubsub.subscribe(channel)
        logger.info(f"Subscribed to channel: {channel}")

        async for message in pubsub.listen():
            if message["type"] != "message":
                continue

            try:
                data = json.loads(message["data"])
                event_type = data.get("event_type")

                # Filter by event types if specified
                if event_types and event_type not in event_types:
                    continue

                yield data

            except json.JSONDecodeError as e:
                logger.warning(f"Invalid JSON in subscription message: {e}")
                continue

    except Exception as e:
        logger.error(f"Subscription error: {e}")
        raise

    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
        await redis.aclose()
        logger.info(f"Unsubscribed from channel: {channel}")


def _parse_reminder_from_event(data: dict) -> ReminderType | None:
    """Parse ReminderType from event data.

    Args:
        data: Event data dictionary

    Returns:
        ReminderType if data contains reminder fields, None otherwise
    """
    from datetime import datetime

    # For DELETE events, we don't have full reminder data
    if data.get("event_type") == "DELETED":
        return None

    try:
        # Parse datetime fields
        remind_at = None
        if data.get("remind_at"):
            remind_at = datetime.fromisoformat(data["remind_at"])

        created_at = datetime.fromisoformat(data["created_at"])
        updated_at = datetime.fromisoformat(data["updated_at"])

        return ReminderType(
            id=strawberry.ID(data["id"]),
            title=data["title"],
            description=data.get("description"),
            remind_at=remind_at,
            is_completed=data.get("is_completed", False),
            created_at=created_at,
            updated_at=updated_at,
        )
    except (KeyError, ValueError) as e:
        logger.warning(f"Failed to parse reminder from event: {e}")
        return None


@strawberry.type(description="Root subscription type")
class Subscription:
    """GraphQL Subscription resolvers.

    Subscriptions use WebSocket transport and Redis PubSub for
    cross-instance event broadcasting.
    """

    @strawberry.subscription(description="Subscribe to reminder events")
    async def reminder_events(
        self,
        info: Info[GraphQLContext, None],  # noqa: ARG002 - required by Strawberry
        event_types: EventTypesArg = None,
    ) -> AsyncGenerator[ReminderEvent]:
        """Subscribe to reminder events.

        Yields ReminderEvent objects when reminders are created, updated,
        completed, or deleted.

        Args:
            info: Strawberry info with context
            event_types: Optional list of event types to filter by

        Yields:
            ReminderEvent objects
        """
        async for data in _subscribe_to_channel("graphql:reminders", event_types):
            event_type_str = data.get("event_type", "UPDATED")

            # Map string to enum
            try:
                event_type = ReminderEventType(event_type_str)
            except ValueError:
                event_type = ReminderEventType.UPDATED

            # Parse reminder data
            reminder = _parse_reminder_from_event(data)
            reminder_id = strawberry.ID(data.get("id", ""))

            yield ReminderEvent(
                event_type=event_type,
                reminder=reminder,
                reminder_id=reminder_id,
            )


__all__ = ["Subscription"]
