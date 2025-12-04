"""Poison message detection for DLQ.

This module provides detection of "poison messages" - messages that
repeatedly fail with the same error and would cause retry storms.

A message is considered "poison" when:
1. The same message body fails multiple times
2. The error signature matches across failures
3. The failure count exceeds a threshold

This prevents wasting resources on messages that will never succeed
while still allowing transient failures to be retried.

Design decisions:
- Uses bounded LRU-style cache to prevent memory growth
- Message hash computed from body for content-based tracking
- Error signature includes type and truncated message
- Thread-safe for concurrent message processing
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from typing import Final

# ============================================================================
# Constants
# ============================================================================

# Default threshold for poison detection
DEFAULT_POISON_THRESHOLD: Final[int] = 3

# Maximum cache size to prevent memory growth
DEFAULT_MAX_CACHE_SIZE: Final[int] = 10000

# Maximum error signature length
MAX_ERROR_SIGNATURE_LENGTH: Final[int] = 200


# ============================================================================
# Poison Message Detector
# ============================================================================


class PoisonMessageDetector:
    """Detect messages that repeatedly fail with the same error.

    Uses a bounded cache to track message failures. When a message
    (identified by content hash) fails with the same error signature
    multiple times, it's classified as "poison" and should be routed
    directly to DLQ.

    The cache uses LRU eviction to bound memory usage:
    - Most recent failures are kept
    - Old entries are evicted when cache is full

    Thread-safe for concurrent message processing.

    Example:
        detector = PoisonMessageDetector(threshold=3)

        # First failure - not poison yet
        assert not detector.check_and_record(msg_body, ValueError("bad"))

        # Second failure - not poison yet
        assert not detector.check_and_record(msg_body, ValueError("bad"))

        # Third failure - NOW it's poison
        assert detector.check_and_record(msg_body, ValueError("bad"))

    Attributes:
        threshold: Number of failures before classifying as poison.
        max_cache_size: Maximum entries in the tracking cache.
    """

    def __init__(
        self,
        threshold: int = DEFAULT_POISON_THRESHOLD,
        max_cache_size: int = DEFAULT_MAX_CACHE_SIZE,
    ) -> None:
        """Initialize poison message detector.

        Args:
            threshold: Number of failures before classifying as poison.
            max_cache_size: Maximum entries in the tracking cache.
        """
        self.threshold = threshold
        self.max_cache_size = max_cache_size

        # LRU cache: {message_hash: (failure_count, error_signature)}
        # Using OrderedDict for LRU ordering
        self._cache: OrderedDict[str, tuple[int, str]] = OrderedDict()
        self._lock = threading.Lock()

    def check_and_record(self, message_body: bytes, error: Exception) -> bool:
        """Check if message is poison and record the failure.

        This method both checks the current state and records the new
        failure atomically. Thread-safe.

        Args:
            message_body: Raw message body bytes.
            error: Exception that caused the failure.

        Returns:
            True if message is detected as poison (failure count >= threshold).
            False if message should continue retrying.

        Example:
            is_poison = detector.check_and_record(msg.body, exc)
            if is_poison:
                route_to_dlq(msg, reason="poison_message")
        """
        msg_hash = self._compute_hash(message_body)
        error_sig = self._compute_error_signature(error)

        with self._lock:
            if msg_hash in self._cache:
                count, prev_sig = self._cache[msg_hash]

                if prev_sig == error_sig:
                    # Same error - increment count
                    new_count = count + 1
                    self._cache[msg_hash] = (new_count, error_sig)
                    # Move to end for LRU ordering
                    self._cache.move_to_end(msg_hash)
                    return new_count >= self.threshold
                else:
                    # Different error - reset count
                    self._cache[msg_hash] = (1, error_sig)
                    self._cache.move_to_end(msg_hash)
                    return False
            else:
                # First failure for this message
                self._evict_if_needed()
                self._cache[msg_hash] = (1, error_sig)
                return False

    def is_poison(self, message_body: bytes) -> bool:
        """Check if a message is currently classified as poison.

        Read-only check without recording a new failure.

        Args:
            message_body: Raw message body bytes.

        Returns:
            True if message has reached poison threshold.
        """
        msg_hash = self._compute_hash(message_body)

        with self._lock:
            if msg_hash in self._cache:
                count, _ = self._cache[msg_hash]
                return count >= self.threshold
            return False

    def clear_message(self, message_body: bytes) -> bool:
        """Clear tracking data for a specific message.

        Use this when a message is successfully processed or
        manually acknowledged.

        Args:
            message_body: Raw message body bytes.

        Returns:
            True if message was being tracked, False otherwise.
        """
        msg_hash = self._compute_hash(message_body)

        with self._lock:
            if msg_hash in self._cache:
                del self._cache[msg_hash]
                return True
            return False

    def clear_all(self) -> int:
        """Clear all tracking data.

        Useful for testing or resetting state.

        Returns:
            Number of entries cleared.
        """
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            return count

    def get_stats(self) -> dict[str, int]:
        """Get detector statistics.

        Returns:
            Dictionary with cache statistics.
        """
        with self._lock:
            total = len(self._cache)
            poison_count = sum(
                1 for count, _ in self._cache.values() if count >= self.threshold
            )
            return {
                "total_tracked": total,
                "poison_messages": poison_count,
                "max_cache_size": self.max_cache_size,
                "threshold": self.threshold,
            }

    def _compute_hash(self, message_body: bytes) -> str:
        """Compute stable hash of message body.

        Uses SHA-256 truncated to 16 chars for memory efficiency
        while maintaining very low collision probability.

        Args:
            message_body: Raw message bytes.

        Returns:
            Truncated hash string.
        """
        return hashlib.sha256(message_body).hexdigest()[:16]

    def _compute_error_signature(self, error: Exception) -> str:
        """Compute error signature for comparison.

        Combines exception type and truncated message to identify
        "same" errors for poison detection.

        Args:
            error: Exception instance.

        Returns:
            Error signature string.
        """
        exc_type = type(error).__name__
        exc_msg = str(error)[:MAX_ERROR_SIGNATURE_LENGTH]
        return f"{exc_type}:{exc_msg}"

    def _evict_if_needed(self) -> None:
        """Evict oldest entries if cache is full.

        Removes 10% of oldest entries to make room for new ones.
        Must be called with lock held.
        """
        if len(self._cache) >= self.max_cache_size:
            # Remove oldest 10% of entries
            evict_count = max(1, self.max_cache_size // 10)
            for _ in range(evict_count):
                self._cache.popitem(last=False)  # FIFO removal


__all__ = [
    "DEFAULT_MAX_CACHE_SIZE",
    "DEFAULT_POISON_THRESHOLD",
    "PoisonMessageDetector",
]
