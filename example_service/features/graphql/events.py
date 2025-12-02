"""Event publishing utilities for GraphQL subscriptions.

Provides helpers for publishing events to Redis PubSub channels,
enabling real-time subscriptions across all features.

Usage in mutation resolvers:
    from example_service.features.graphql.events import publish_event

    # After creating/updating a resource
    await publish_event(
        channel="graphql:tags",
        event_type="CREATED",
        data=tag_dict,
    )
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def publish_event(
    channel: str,
    event_type: str,
    data: dict[str, Any],
) -> None:
    """Publish an event to Redis PubSub for GraphQL subscriptions.

    This function is called from mutation resolvers to notify subscribers
    of data changes. Events are published to Redis channels and consumed
    by subscription resolvers.

    Args:
        channel: Redis channel name (e.g., "graphql:tags", "graphql:files")
        event_type: Type of event (e.g., "CREATED", "UPDATED", "DELETED")
        data: Serialized data dictionary (must be JSON-serializable)

    Example:
        await publish_event(
            channel="graphql:feature_flags",
            event_type="TOGGLED",
            data={
                "id": str(flag.id),
                "key": flag.key,
                "enabled": flag.enabled,
                "previous_enabled": old_enabled,
                ...
            },
        )
    """
    try:
        from redis.asyncio import Redis

        from example_service.core.settings import get_redis_settings

        redis_settings = get_redis_settings()
        if not redis_settings.is_configured:
            logger.debug("Redis not configured, skipping subscription publish")
            return

        redis = Redis.from_url(str(redis_settings.url))
        try:
            payload = json.dumps(
                {
                    "event_type": event_type,
                    **data,
                }
            )

            await redis.publish(channel, payload)
            logger.debug(f"Published {event_type} event to {channel}")

        finally:
            await redis.close()

    except Exception as e:
        # Don't fail mutations if event publishing fails
        logger.exception(f"Failed to publish event to {channel}: {e}")


async def publish_reminder_event(event_type: str, reminder_data: dict[str, Any]) -> None:
    """Publish a reminder event.

    Args:
        event_type: CREATED, UPDATED, COMPLETED, or DELETED
        reminder_data: Serialized reminder dictionary
    """
    await publish_event("graphql:reminders", event_type, reminder_data)


async def publish_tag_event(event_type: str, tag_data: dict[str, Any]) -> None:
    """Publish a tag event.

    Args:
        event_type: CREATED, UPDATED, or DELETED
        tag_data: Serialized tag dictionary
    """
    await publish_event("graphql:tags", event_type, tag_data)


async def publish_feature_flag_event(
    event_type: str,
    flag_data: dict[str, Any],
    previous_enabled: bool | None = None,
) -> None:
    """Publish a feature flag event.

    Args:
        event_type: CREATED, UPDATED, TOGGLED, or DELETED
        flag_data: Serialized flag dictionary
        previous_enabled: Previous enabled state (for TOGGLED events)
    """
    if previous_enabled is not None:
        flag_data["previous_enabled"] = previous_enabled

    await publish_event("graphql:feature_flags", event_type, flag_data)


async def publish_file_event(
    event_type: str,
    file_data: dict[str, Any],
    error_message: str | None = None,
) -> None:
    """Publish a file event.

    Args:
        event_type: UPLOADED, READY, FAILED, or DELETED
        file_data: Serialized file dictionary
        error_message: Error message (for FAILED events)
    """
    if error_message:
        file_data["error_message"] = error_message

    await publish_event("graphql:files", event_type, file_data)


async def publish_webhook_delivery_event(
    event_type: str,
    delivery_data: dict[str, Any],
) -> None:
    """Publish a webhook delivery event.

    Args:
        event_type: DELIVERED, FAILED, or RETRYING
        delivery_data: Serialized delivery dictionary
    """
    await publish_event("graphql:webhook_deliveries", event_type, delivery_data)


def serialize_model_for_event(model: Any) -> dict[str, Any]:
    """Serialize a SQLAlchemy model to a dictionary for event publishing.

    Handles datetime serialization and converts UUIDs to strings.

    Args:
        model: SQLAlchemy model instance

    Returns:
        Dictionary with JSON-serializable values
    """
    from datetime import datetime
    from uuid import UUID

    result: dict[str, Any] = {}

    # Get all columns from the model
    for column in model.__table__.columns:
        value = getattr(model, column.name, None)

        # Convert non-serializable types
        if isinstance(value, datetime):
            result[column.name] = value.isoformat()
        elif isinstance(value, UUID):
            result[column.name] = str(value)
        elif value is None:
            result[column.name] = None
        else:
            result[column.name] = value

    return result


__all__ = [
    "publish_event",
    "publish_feature_flag_event",
    "publish_file_event",
    "publish_reminder_event",
    "publish_tag_event",
    "publish_webhook_delivery_event",
    "serialize_model_for_event",
]
