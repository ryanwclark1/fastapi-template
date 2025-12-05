"""Common validator utilities.

This module provides shared utilities for building validators.
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


__all__ = ["optional_validator"]
