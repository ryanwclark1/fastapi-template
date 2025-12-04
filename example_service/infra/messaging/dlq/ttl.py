"""Message TTL (Time-To-Live) handling for DLQ.

This module provides utilities for tracking and checking message TTL
to prevent stale messages from being endlessly retried.

TTL is tracked via message headers:
- x-message-timestamp-ms: Unix timestamp when message was first published
- x-message-ttl-ms: Maximum lifetime for the message (optional override)

When a message exceeds its TTL, it should be routed to DLQ rather than
continuing retry attempts.
"""

from __future__ import annotations

import time
from typing import Any, Final

# ============================================================================
# Header Constants
# ============================================================================

MESSAGE_TIMESTAMP_HEADER: Final[str] = "x-message-timestamp-ms"
MESSAGE_TTL_HEADER: Final[str] = "x-message-ttl-ms"

# Default TTL: 24 hours
DEFAULT_MESSAGE_TTL_MS: Final[int] = 24 * 60 * 60 * 1000

# Minimum TTL: 1 minute
MIN_MESSAGE_TTL_MS: Final[int] = 60 * 1000


# ============================================================================
# TTL Functions
# ============================================================================


def is_message_expired(
    headers: dict[str, Any] | None,
    ttl_ms: int | None = None,
) -> bool:
    """Check if a message has exceeded its TTL.

    Uses the x-message-timestamp-ms header to determine when the message
    was first published, then compares against the current time.

    TTL precedence:
    1. Explicit ttl_ms parameter
    2. x-message-ttl-ms header
    3. Default TTL (24 hours)

    Args:
        headers: Message headers dictionary (may be None).
        ttl_ms: Optional TTL override in milliseconds.

    Returns:
        True if message has exceeded its TTL, False otherwise.
        Returns False if no timestamp header is present.

    Example:
        headers = {"x-message-timestamp-ms": str(old_timestamp)}
        if is_message_expired(headers, ttl_ms=3600000):  # 1 hour TTL
            route_to_dlq(msg, reason="message_expired")
    """
    if not headers:
        return False

    # Get original timestamp
    timestamp_str = headers.get(MESSAGE_TIMESTAMP_HEADER)
    if not timestamp_str:
        return False

    try:
        timestamp_ms = int(timestamp_str)
    except (ValueError, TypeError):
        return False

    # Determine TTL
    effective_ttl = _get_effective_ttl(headers, ttl_ms)

    # Check expiration
    now_ms = int(time.time() * 1000)
    age_ms = now_ms - timestamp_ms

    return age_ms > effective_ttl


def get_message_age_ms(headers: dict[str, Any] | None) -> int | None:
    """Get the age of a message in milliseconds.

    Args:
        headers: Message headers dictionary.

    Returns:
        Message age in milliseconds, or None if no timestamp.
    """
    if not headers:
        return None

    timestamp_str = headers.get(MESSAGE_TIMESTAMP_HEADER)
    if not timestamp_str:
        return None

    try:
        timestamp_ms = int(timestamp_str)
        now_ms = int(time.time() * 1000)
        return now_ms - timestamp_ms
    except (ValueError, TypeError):
        return None


def get_remaining_ttl_ms(
    headers: dict[str, Any] | None,
    ttl_ms: int | None = None,
) -> int | None:
    """Get remaining TTL for a message in milliseconds.

    Args:
        headers: Message headers dictionary.
        ttl_ms: Optional TTL override.

    Returns:
        Remaining TTL in milliseconds (may be negative if expired),
        or None if no timestamp.
    """
    age = get_message_age_ms(headers)
    if age is None:
        return None

    effective_ttl = _get_effective_ttl(headers, ttl_ms)
    return effective_ttl - age


def add_timestamp_header(headers: dict[str, Any] | None = None) -> dict[str, Any]:
    """Add timestamp header to message headers.

    Should be called when first publishing a message to track TTL.

    Args:
        headers: Existing headers dictionary (modified in place).
                 Creates new dict if None.

    Returns:
        Headers dictionary with timestamp added.

    Example:
        headers = add_timestamp_header()
        await broker.publish(data, headers=headers)
    """
    if headers is None:
        headers = {}

    if MESSAGE_TIMESTAMP_HEADER not in headers:
        headers[MESSAGE_TIMESTAMP_HEADER] = str(int(time.time() * 1000))

    return headers


def add_ttl_header(
    headers: dict[str, Any] | None = None,
    ttl_ms: int = DEFAULT_MESSAGE_TTL_MS,
) -> dict[str, Any]:
    """Add TTL header to message headers.

    Use this to set a custom TTL for specific messages.

    Args:
        headers: Existing headers dictionary (modified in place).
        ttl_ms: TTL in milliseconds.

    Returns:
        Headers dictionary with TTL added.

    Example:
        # Short-lived notification with 1 hour TTL
        headers = add_ttl_header(ttl_ms=3600000)
        await broker.publish(notification, headers=headers)
    """
    if headers is None:
        headers = {}

    # Ensure TTL is at least minimum
    effective_ttl = max(ttl_ms, MIN_MESSAGE_TTL_MS)
    headers[MESSAGE_TTL_HEADER] = str(effective_ttl)

    return headers


def _get_effective_ttl(
    headers: dict[str, Any] | None,
    override_ttl: int | None,
) -> int:
    """Get the effective TTL for a message.

    Priority:
    1. override_ttl parameter
    2. x-message-ttl-ms header
    3. DEFAULT_MESSAGE_TTL_MS

    Args:
        headers: Message headers.
        override_ttl: TTL override from config.

    Returns:
        Effective TTL in milliseconds.
    """
    # Priority 1: Override parameter
    if override_ttl is not None:
        return max(override_ttl, MIN_MESSAGE_TTL_MS)

    # Priority 2: Header value
    if headers:
        ttl_str = headers.get(MESSAGE_TTL_HEADER)
        if ttl_str:
            try:
                return max(int(ttl_str), MIN_MESSAGE_TTL_MS)
            except (ValueError, TypeError):
                pass

    # Priority 3: Default
    return DEFAULT_MESSAGE_TTL_MS


__all__ = [
    # Constants
    "DEFAULT_MESSAGE_TTL_MS",
    "MESSAGE_TIMESTAMP_HEADER",
    "MESSAGE_TTL_HEADER",
    "MIN_MESSAGE_TTL_MS",
    # Functions
    "add_timestamp_header",
    "add_ttl_header",
    "get_message_age_ms",
    "get_remaining_ttl_ms",
    "is_message_expired",
]
