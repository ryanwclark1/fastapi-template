"""Non-retryable exception registry for DLQ.

This module provides a thread-safe registry of exception types that should
not be retried because they represent permanent failures (e.g., validation
errors, malformed data, business logic violations).

Design decisions:
- Uses set-based lookup for O(1) average case performance
- Thread-safe with threading.Lock for concurrent access
- Checks by exception class name (string) for simplicity and serialization
- Allows runtime registration of custom non-retryable exceptions
"""

from __future__ import annotations

import threading

# ─────────────────────────────────────────────────────
# Thread-safe registry
# ─────────────────────────────────────────────────────

# Default non-retryable exceptions (permanent failures)
# These represent data/logic errors that won't succeed on retry
_DEFAULT_NON_RETRYABLE: frozenset[str] = frozenset(
    {
        # Python built-in errors (data/logic issues)
        "ValueError",
        "TypeError",
        "KeyError",
        "AttributeError",
        "IndexError",
        "AssertionError",
        # JSON/serialization errors
        "JSONDecodeError",
        # Pydantic validation
        "ValidationError",
        # Generic programming errors
        "NotImplementedError",
        "RuntimeError",
    },
)

# Mutable set for runtime additions (protected by lock)
_custom_non_retryable: set[str] = set()
_lock = threading.Lock()


def register_non_retryable(*exception_classes: type[Exception]) -> None:
    """Register exception types that should not be retried.

    Thread-safe function to add custom exception types to the
    non-retryable registry. These exceptions will be routed
    directly to DLQ without retry attempts.

    Use this for application-specific permanent failures like:
    - Custom validation errors
    - Business logic violations
    - Authorization failures

    Args:
        *exception_classes: Exception classes to register.

    Example:
        # Register custom exceptions as non-retryable
        class InsufficientFundsError(Exception):
            pass

        class InvalidOrderError(Exception):
            pass

        register_non_retryable(InsufficientFundsError, InvalidOrderError)

        # Now these will skip retry and go directly to DLQ
        assert is_non_retryable_exception(InsufficientFundsError("no funds"))
    """
    with _lock:
        for exc_class in exception_classes:
            _custom_non_retryable.add(exc_class.__name__)


def unregister_non_retryable(*exception_classes: type[Exception]) -> None:
    """Remove exception types from the non-retryable registry.

    Thread-safe function to remove previously registered exception types.
    Note: Cannot remove default non-retryable exceptions.

    Args:
        *exception_classes: Exception classes to unregister.

    Example:
        unregister_non_retryable(MyCustomError)
    """
    with _lock:
        for exc_class in exception_classes:
            _custom_non_retryable.discard(exc_class.__name__)


def is_non_retryable_exception(exception: Exception) -> bool:
    """Check if an exception should skip retry logic.

    Uses O(1) set lookup for fast classification of exceptions.
    Checks both default and custom registered non-retryable types.

    Args:
        exception: The exception to check.

    Returns:
        True if exception should NOT be retried (route to DLQ).
        False if exception should be retried.

    Example:
        # Validation error - don't retry
        assert is_non_retryable_exception(ValueError("invalid input"))

        # Timeout error - retry
        assert not is_non_retryable_exception(TimeoutError("timeout"))
    """
    exc_name = type(exception).__name__

    # Check default non-retryable (frozenset - no lock needed)
    if exc_name in _DEFAULT_NON_RETRYABLE:
        return True

    # Check custom registered (needs lock for thread safety)
    with _lock:
        return exc_name in _custom_non_retryable


def is_non_retryable_by_name(exception_name: str) -> bool:
    """Check if an exception name is non-retryable.

    Useful when you only have the exception name (e.g., from headers).

    Args:
        exception_name: The exception class name to check.

    Returns:
        True if exception should NOT be retried.

    Example:
        assert is_non_retryable_by_name("ValueError")
        assert not is_non_retryable_by_name("TimeoutError")
    """
    if exception_name in _DEFAULT_NON_RETRYABLE:
        return True

    with _lock:
        return exception_name in _custom_non_retryable


def get_all_non_retryable() -> frozenset[str]:
    """Get all non-retryable exception names (default + custom).

    Returns a snapshot of the current registry. The returned frozenset
    is thread-safe to iterate without holding the lock.

    Returns:
        Frozenset of exception class names.

    Example:
        non_retryable = get_all_non_retryable()
        print(f"Non-retryable exceptions: {non_retryable}")
    """
    with _lock:
        return _DEFAULT_NON_RETRYABLE | frozenset(_custom_non_retryable)


def clear_custom_non_retryable() -> None:
    """Clear all custom registered non-retryable exceptions.

    Useful for testing or resetting state. Does NOT clear defaults.

    Example:
        clear_custom_non_retryable()
    """
    with _lock:
        _custom_non_retryable.clear()


__all__ = [
    "clear_custom_non_retryable",
    "get_all_non_retryable",
    "is_non_retryable_by_name",
    "is_non_retryable_exception",
    "register_non_retryable",
    "unregister_non_retryable",
]
