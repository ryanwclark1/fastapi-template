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

# Re-export all validators for backward compatibility
from example_service.core.validators.common import optional_validator
from example_service.core.validators.rrule import (
    validate_rrule_optional,
    validate_rrule_string,
)
from example_service.core.validators.webhooks import (
    RESERVED_WEBHOOK_HEADERS,
    validate_custom_headers,
    validate_custom_headers_optional,
    validate_event_types,
    validate_event_types_optional,
)

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
