"""Exchange and queue naming conventions for messaging infrastructure.

This module centralizes naming conventions for exchanges, queues, and routing keys,
following patterns similar to accent-hub for consistency across services.

All naming functions use `rabbit_settings` for prefixing to support multi-environment
deployments (dev, staging, production).
"""

from __future__ import annotations

from example_service.core.settings import get_rabbit_settings

# Get RabbitMQ settings for prefixing
rabbit_settings = get_rabbit_settings()

# ──────────────────────────────────────────────────────────────────────────────
# Exchange Name Constants
# ──────────────────────────────────────────────────────────────────────────────

DOMAIN_EVENTS_EXCHANGE_NAME: str = rabbit_settings.exchange_name
"""Default domain events exchange name.

This is the primary exchange for domain events. Uses the exchange_name
from RabbitSettings, which defaults to "example-service".
"""

DLQ_EXCHANGE_NAME: str = f"{rabbit_settings.queue_prefix}.dlq"
"""Dead Letter Queue exchange name.

All failed messages after max retries are routed to this exchange.
Format: {queue_prefix}.dlq (e.g., "example-service.dlq")
"""

INTEGRATIONS_EXCHANGE_NAME: str = f"{rabbit_settings.queue_prefix}.integrations"
"""Integrations exchange name.

For events related to external service integrations.
Format: {queue_prefix}.integrations
"""

NOTIFICATIONS_EXCHANGE_NAME: str = f"{rabbit_settings.queue_prefix}.notifications"
"""Notifications exchange name.

For notification events (email, SMS, push notifications).
Format: {queue_prefix}.notifications
"""


# ──────────────────────────────────────────────────────────────────────────────
# Queue Name Helpers
# ──────────────────────────────────────────────────────────────────────────────


def get_queue_name(base_name: str) -> str:
    """Get fully qualified queue name with prefix.

    Args:
        base_name: Base queue name (e.g., "example-events").

    Returns:
        Prefixed queue name (e.g., "example-service.example-events").

    Example:
        >>> queue_name = get_queue_name("example-events")
        >>> # Returns: "example-service.example-events"
    """
    return rabbit_settings.get_prefixed_queue(base_name)


def get_domain_events_exchange_name() -> str:
    """Get domain events exchange name.

    Returns:
        Domain events exchange name from settings.
    """
    return DOMAIN_EVENTS_EXCHANGE_NAME


def get_dlq_exchange_name() -> str:
    """Get Dead Letter Queue exchange name.

    Returns:
        DLQ exchange name with prefix.
    """
    return DLQ_EXCHANGE_NAME


def get_integrations_exchange_name() -> str:
    """Get integrations exchange name.

    Returns:
        Integrations exchange name with prefix.
    """
    return INTEGRATIONS_EXCHANGE_NAME


def get_notifications_exchange_name() -> str:
    """Get notifications exchange name.

    Returns:
        Notifications exchange name with prefix.
    """
    return NOTIFICATIONS_EXCHANGE_NAME


# ──────────────────────────────────────────────────────────────────────────────
# Routing Key Helpers
# ──────────────────────────────────────────────────────────────────────────────


def get_routing_key(event_type: str, tenant_id: str | None = None) -> str:
    """Generate routing key for event type.

    Args:
        event_type: Event type (e.g., "example.created").
        tenant_id: Optional tenant ID for tenant-specific routing.

    Returns:
        Routing key (e.g., "example.created" or "example.created.tenant-123").

    Example:
        >>> key = get_routing_key("example.created")
        >>> # Returns: "example.created"
        >>>
        >>> key = get_routing_key("example.created", tenant_id="tenant-123")
        >>> # Returns: "example.created.tenant-123"
    """
    if tenant_id:
        return f"{event_type}.{tenant_id}"
    return event_type


def get_routing_key_pattern(event_type_prefix: str) -> str:
    """Generate routing key pattern for topic exchange.

    Args:
        event_type_prefix: Event type prefix (e.g., "example").

    Returns:
        Routing key pattern (e.g., "example.*").

    Example:
        >>> pattern = get_routing_key_pattern("example")
        >>> # Returns: "example.*"
        >>> # Matches: "example.created", "example.updated", etc.
    """
    return f"{event_type_prefix}.*"


def get_tenant_routing_key_pattern(event_type_prefix: str, tenant_id: str) -> str:
    """Generate tenant-specific routing key pattern.

    Args:
        event_type_prefix: Event type prefix (e.g., "example").
        tenant_id: Tenant ID.

    Returns:
        Routing key pattern (e.g., "example.*.tenant-123").

    Example:
        >>> pattern = get_tenant_routing_key_pattern("example", "tenant-123")
        >>> # Returns: "example.*.tenant-123"
        >>> # Matches: "example.created.tenant-123", "example.updated.tenant-123", etc.
    """
    return f"{event_type_prefix}.*.{tenant_id}"


# ──────────────────────────────────────────────────────────────────────────────
# Common Queue Names
# ──────────────────────────────────────────────────────────────────────────────

EXAMPLE_EVENTS_QUEUE_NAME: str = get_queue_name("example-events")
"""Example events queue name with prefix."""

DLQ_QUEUE_NAME: str = get_queue_name("dlq")
"""Dead Letter Queue name with prefix."""
