"""Webhook validators.

This module provides validation functions for webhook-related schemas,
including event types and custom headers.
"""

from __future__ import annotations

from example_service.core.validators.common import optional_validator

# Headers that cannot be overridden by custom headers
RESERVED_WEBHOOK_HEADERS: frozenset[str] = frozenset(
    {
        "x-webhook-signature",
        "x-webhook-timestamp",
        "x-webhook-event-type",
        "x-webhook-event-id",
        "content-type",
        "user-agent",
    }
)


def validate_event_types(values: list[str]) -> list[str]:
    """Validate event types are non-empty strings.

    Strips whitespace from each event type and validates that
    none of them are empty after stripping.

    Args:
        values: List of event type strings.

    Returns:
        List of stripped event type strings.

    Raises:
        ValueError: If any event type is empty after stripping.
    """
    if not all(event_type.strip() for event_type in values):
        raise ValueError("Event types cannot be empty strings")
    return [event_type.strip() for event_type in values]


# Optional version for Update schemas
validate_event_types_optional = optional_validator(validate_event_types)


def validate_custom_headers(headers: dict[str, str]) -> dict[str, str]:
    """Validate custom headers don't override reserved headers.

    System headers like signature, timestamp, and content-type
    must be controlled by the webhook system, not user configuration.

    Args:
        headers: Dictionary of custom header names to values.

    Returns:
        The validated headers dictionary.

    Raises:
        ValueError: If any header name matches a reserved header.
    """
    for header_name in headers:
        if header_name.lower() in RESERVED_WEBHOOK_HEADERS:
            raise ValueError(f"Cannot override reserved header: {header_name}")
    return headers


# Optional version for Update schemas
validate_custom_headers_optional = optional_validator(validate_custom_headers)


__all__ = [
    "RESERVED_WEBHOOK_HEADERS",
    "validate_custom_headers",
    "validate_custom_headers_optional",
    "validate_event_types",
    "validate_event_types_optional",
]
