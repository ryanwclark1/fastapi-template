"""Reusable Pydantic validators for schema classes.

This module provides shared validation functions that can be used
across multiple Pydantic schemas to avoid code duplication.

Usage with Pydantic v2:
    from example_service.core.validators import validate_rrule_optional

    class ReminderCreate(BaseModel):
        recurrence_rule: str | None = None

        @field_validator("recurrence_rule")
        @classmethod
        def validate_rule(cls, v: str | None) -> str | None:
            return validate_rrule_optional(v)

For simple cases, you can also use the validators directly:
    from example_service.core.validators import validate_event_types

    # In a route or service
    cleaned_types = validate_event_types(event_types)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable

T = TypeVar("T")


def optional_validator(
    validate_fn: Callable[[T], T],
) -> Callable[[T | None], T | None]:
    """Wrap a validator to handle None values.

    This is useful when the same validation logic needs to be applied
    to both required fields (in Create schemas) and optional fields
    (in Update schemas).

    Args:
        validate_fn: Validator function that handles non-None values.

    Returns:
        Wrapped validator that passes None through unchanged.

    Example:
        validate_rrule_optional = optional_validator(validate_rrule_string)
    """

    def wrapper(value: T | None) -> T | None:
        if value is None:
            return None
        return validate_fn(value)

    return wrapper


# ─────────────────────────────────────────────────────────────────────────────
# RRULE Validators (for reminders)
# ─────────────────────────────────────────────────────────────────────────────


def validate_rrule_string(value: str) -> str:
    """Validate an iCalendar RRULE string.

    Args:
        value: RRULE string to validate.

    Returns:
        The validated RRULE string.

    Raises:
        ValueError: If the RRULE string is invalid.
    """
    # Lazy import to avoid circular dependencies
    from example_service.features.reminders.recurrence import validate_rrule

    is_valid, error = validate_rrule(value)
    if not is_valid:
        raise ValueError(f"Invalid RRULE: {error}")
    return value


# Optional version that passes None through
validate_rrule_optional = optional_validator(validate_rrule_string)


# ─────────────────────────────────────────────────────────────────────────────
# Event Type Validators (for webhooks)
# ─────────────────────────────────────────────────────────────────────────────


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


# ─────────────────────────────────────────────────────────────────────────────
# Custom Headers Validators (for webhooks)
# ─────────────────────────────────────────────────────────────────────────────

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
    # Generic utilities
    "optional_validator",
    # Custom headers validators
    "validate_custom_headers",
    "validate_custom_headers_optional",
    # Event type validators
    "validate_event_types",
    "validate_event_types_optional",
    "validate_rrule_optional",
    # RRULE validators
    "validate_rrule_string",
]
