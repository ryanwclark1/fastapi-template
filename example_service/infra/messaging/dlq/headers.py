"""Retry state header serialization for DLQ.

This module provides header-based retry state tracking that persists
across message republishing. The retry state is stored in message headers
to survive broker restarts and allow distributed tracking.

Design decisions:
- Uses frozen dataclass with slots for minimal memory footprint
- All header values are strings for AMQP compatibility
- Error messages are truncated to prevent header bloat
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

# ─────────────────────────────────────────────────────
# Header key constants (x- prefix for custom headers)
# ─────────────────────────────────────────────────────
RETRY_COUNT_HEADER = "x-retry-count"
RETRY_FIRST_ATTEMPT_HEADER = "x-retry-first-attempt-ms"
RETRY_TOTAL_DELAY_HEADER = "x-retry-total-delay-ms"
RETRY_LAST_ERROR_HEADER = "x-retry-last-error"
RETRY_LAST_ERROR_TYPE_HEADER = "x-retry-last-error-type"
RETRY_LAST_ATTEMPT_HEADER = "x-retry-last-attempt-ms"

# Maximum error message length to prevent header bloat
MAX_ERROR_LENGTH = 500


@dataclass(frozen=True, slots=True)
class RetryState:
    """Immutable retry state extracted from/stored to message headers.

    This dataclass tracks the retry history for a message, allowing
    the DLQ middleware to make informed decisions about whether to
    retry, how long to delay, and when to give up.

    The frozen=True and slots=True optimizations provide:
    - Thread safety (immutable)
    - 15-20% memory reduction (slots)
    - Hashability for use in sets/dicts

    Attributes:
        count: Number of retry attempts made.
        first_attempt_ms: Unix timestamp (ms) of first failure.
        total_delay_ms: Total delay accumulated across retries.
        last_error: Truncated error message from last failure.
        last_error_type: Exception class name from last failure.
        last_attempt_ms: Unix timestamp (ms) of last retry attempt.

    Example:
        # Extract from incoming message
        state = RetryState.from_headers(msg.headers)

        # Check retry count
        if state.count >= max_retries:
            route_to_dlq(msg)
        else:
            # Increment and republish
            new_state = state.increment(delay_ms=2000, error=exc)
            await broker.publish(msg.body, headers=new_state.to_headers())
    """

    count: int = 0
    first_attempt_ms: int = 0
    total_delay_ms: int = 0
    last_error: str = ""
    last_error_type: str = ""
    last_attempt_ms: int = 0

    @classmethod
    def from_headers(cls, headers: dict[str, Any] | None) -> RetryState:
        """Extract retry state from message headers.

        Safely parses header values with fallbacks for missing or
        malformed data. This allows the middleware to handle messages
        that weren't originally published with retry headers.

        Args:
            headers: Message headers dictionary (may be None).

        Returns:
            RetryState instance with values from headers or defaults.

        Example:
            # Message with retry history
            headers = {"x-retry-count": "2", "x-retry-total-delay-ms": "3000"}
            state = RetryState.from_headers(headers)
            assert state.count == 2

            # Fresh message (no headers)
            state = RetryState.from_headers(None)
            assert state.count == 0
        """
        if not headers:
            return cls()

        return cls(
            count=_safe_int(headers.get(RETRY_COUNT_HEADER), default=0),
            first_attempt_ms=_safe_int(
                headers.get(RETRY_FIRST_ATTEMPT_HEADER), default=0
            ),
            total_delay_ms=_safe_int(headers.get(RETRY_TOTAL_DELAY_HEADER), default=0),
            last_error=str(headers.get(RETRY_LAST_ERROR_HEADER, ""))[:MAX_ERROR_LENGTH],
            last_error_type=str(headers.get(RETRY_LAST_ERROR_TYPE_HEADER, "")),
            last_attempt_ms=_safe_int(headers.get(RETRY_LAST_ATTEMPT_HEADER), default=0),
        )

    def to_headers(self) -> dict[str, str]:
        """Convert retry state to message headers.

        All values are converted to strings for AMQP header compatibility.
        Empty values are still included to allow proper tracking.

        Returns:
            Dictionary of header key-value pairs (all strings).

        Example:
            state = RetryState(count=2, total_delay_ms=3000)
            headers = state.to_headers()
            # {"x-retry-count": "2", "x-retry-total-delay-ms": "3000", ...}
        """
        return {
            RETRY_COUNT_HEADER: str(self.count),
            RETRY_FIRST_ATTEMPT_HEADER: str(self.first_attempt_ms),
            RETRY_TOTAL_DELAY_HEADER: str(self.total_delay_ms),
            RETRY_LAST_ERROR_HEADER: self.last_error[:MAX_ERROR_LENGTH],
            RETRY_LAST_ERROR_TYPE_HEADER: self.last_error_type,
            RETRY_LAST_ATTEMPT_HEADER: str(self.last_attempt_ms),
        }

    def increment(
        self,
        delay_ms: int,
        error: Exception,
    ) -> RetryState:
        """Create a new state with incremented retry count.

        Since RetryState is frozen, this returns a new instance with
        updated values rather than mutating in place.

        Args:
            delay_ms: Delay in milliseconds before this retry.
            error: Exception that caused the retry.

        Returns:
            New RetryState with incremented count and updated error info.

        Example:
            state = RetryState()
            new_state = state.increment(delay_ms=1000, error=TimeoutError("timeout"))
            assert new_state.count == 1
            assert new_state.total_delay_ms == 1000
            assert new_state.last_error_type == "TimeoutError"
        """
        now_ms = _current_time_ms()

        return RetryState(
            count=self.count + 1,
            first_attempt_ms=self.first_attempt_ms or now_ms,
            total_delay_ms=self.total_delay_ms + delay_ms,
            last_error=str(error)[:MAX_ERROR_LENGTH],
            last_error_type=type(error).__name__,
            last_attempt_ms=now_ms,
        )

    @property
    def elapsed_ms(self) -> int:
        """Calculate elapsed time since first failure.

        Returns:
            Milliseconds since first_attempt_ms, or 0 if no attempts.
        """
        if not self.first_attempt_ms:
            return 0
        return _current_time_ms() - self.first_attempt_ms

    @property
    def first_attempt_time(self) -> datetime | None:
        """Get first attempt as datetime (UTC).

        Returns:
            datetime of first attempt or None if no attempts.
        """
        if not self.first_attempt_ms:
            return None
        return datetime.fromtimestamp(self.first_attempt_ms / 1000, tz=UTC)

    @property
    def last_attempt_time(self) -> datetime | None:
        """Get last attempt as datetime (UTC).

        Returns:
            datetime of last attempt or None if no attempts.
        """
        if not self.last_attempt_ms:
            return None
        return datetime.fromtimestamp(self.last_attempt_ms / 1000, tz=UTC)

    def __repr__(self) -> str:
        """Human-readable representation."""
        return (
            f"RetryState(count={self.count}, "
            f"total_delay_ms={self.total_delay_ms}, "
            f"last_error_type={self.last_error_type!r})"
        )


# ─────────────────────────────────────────────────────
# Helper functions
# ─────────────────────────────────────────────────────


def _safe_int(value: Any, default: int = 0) -> int:
    """Safely convert value to int with fallback.

    Args:
        value: Value to convert (may be str, int, None, or other).
        default: Fallback value if conversion fails.

    Returns:
        Integer value or default.
    """
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _current_time_ms() -> int:
    """Get current Unix timestamp in milliseconds.

    Returns:
        Current time as milliseconds since epoch.
    """
    return int(time.time() * 1000)


__all__ = [
    "RETRY_COUNT_HEADER",
    "RETRY_FIRST_ATTEMPT_HEADER",
    "RETRY_LAST_ATTEMPT_HEADER",
    "RETRY_LAST_ERROR_HEADER",
    "RETRY_LAST_ERROR_TYPE_HEADER",
    "RETRY_TOTAL_DELAY_HEADER",
    "RetryState",
]
