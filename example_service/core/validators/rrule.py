"""RRULE validators for reminder recurrence rules.

This module provides validation functions for iCalendar RRULE strings
used in reminder recurrence functionality.
"""

from __future__ import annotations

from example_service.core.validators.common import optional_validator


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
        msg = f"Invalid RRULE: {error}"
        raise ValueError(msg)
    return value


# Optional version that passes None through
validate_rrule_optional = optional_validator(validate_rrule_string)


__all__ = [
    "validate_rrule_optional",
    "validate_rrule_string",
]
