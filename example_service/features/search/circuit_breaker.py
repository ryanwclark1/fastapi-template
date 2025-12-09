"""Circuit breaker pattern for search cache.

Prevents cascading failures when the cache is unavailable by
temporarily disabling cache operations after repeated failures.

States:
- CLOSED: Normal operation, requests pass through
- OPEN: Failure threshold exceeded, requests are blocked
- HALF_OPEN: Testing if service has recovered

Usage:
    breaker = CircuitBreaker(threshold=5, timeout=30)

    async def get_cached():
        if not breaker.can_execute():
            return None  # Skip cache

        try:
            result = await cache.get(key)
            breaker.record_success()
            return result
        except Exception as e:
            breaker.record_failure()
            raise
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
import logging
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(StrEnum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Blocking requests
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class CircuitBreakerStats:
    """Statistics for a circuit breaker."""

    state: CircuitState
    failure_count: int
    success_count: int
    last_failure_time: datetime | None
    last_success_time: datetime | None
    last_state_change: datetime | None
    total_blocked: int
    total_requests: int

    @property
    def failure_rate(self) -> float:
        """Calculate the failure rate."""
        if self.total_requests == 0:
            return 0.0
        return self.failure_count / self.total_requests


@dataclass
class CircuitBreaker:
    """Circuit breaker for protecting against cascading failures.

    Monitors failures and opens the circuit when the threshold is exceeded,
    preventing further requests until the timeout expires.

    Example:
        breaker = CircuitBreaker(threshold=5, timeout=30)

        # Check if we can execute
        if breaker.can_execute():
            try:
                result = await risky_operation()
                breaker.record_success()
            except Exception:
                breaker.record_failure()
        else:
            # Use fallback
            result = fallback_value

        # Or use the decorator
        @breaker.protect
        async def cached_search(query: str):
            return await cache.get(query)
    """

    threshold: int = 5  # Failures before opening
    timeout: int = 30  # Seconds before half-open
    half_open_max_calls: int = 1  # Max calls in half-open state
    name: str = "default"

    # Internal state
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _success_count: int = field(default=0, init=False)
    _last_failure_time: datetime | None = field(default=None, init=False)
    _last_success_time: datetime | None = field(default=None, init=False)
    _last_state_change: datetime | None = field(default=None, init=False)
    _half_open_calls: int = field(default=0, init=False)
    _total_blocked: int = field(default=0, init=False)
    _total_requests: int = field(default=0, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    @property
    def state(self) -> CircuitState:
        """Get the current circuit state."""
        return self._state

    @property
    def is_closed(self) -> bool:
        """Check if circuit is closed (normal operation)."""
        return self._state == CircuitState.CLOSED

    @property
    def is_open(self) -> bool:
        """Check if circuit is open (blocking requests)."""
        return self._state == CircuitState.OPEN

    @property
    def is_half_open(self) -> bool:
        """Check if circuit is half-open (testing recovery)."""
        return self._state == CircuitState.HALF_OPEN

    def _transition_to(self, new_state: CircuitState) -> None:
        """Transition to a new state.

        Args:
            new_state: The new state.
        """
        if self._state != new_state:
            old_state = self._state
            self._state = new_state
            self._last_state_change = datetime.now(UTC)

            if new_state == CircuitState.HALF_OPEN:
                self._half_open_calls = 0

            logger.info(
                "Circuit breaker '%s' transitioned: %s -> %s",
                self.name,
                old_state,
                new_state,
            )

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset.

        Returns:
            True if we should try half-open state.
        """
        if self._last_failure_time is None:
            return True

        elapsed = datetime.now(UTC) - self._last_failure_time
        return elapsed >= timedelta(seconds=self.timeout)

    def can_execute(self) -> bool:
        """Check if a request can be executed.

        Returns:
            True if the request should proceed.
        """
        self._total_requests += 1

        if self._state == CircuitState.CLOSED:
            return True

        if self._state == CircuitState.OPEN:
            if self._should_attempt_reset():
                self._transition_to(CircuitState.HALF_OPEN)
                return True
            self._total_blocked += 1
            return False

        # Half-open: allow limited calls
        if self._half_open_calls < self.half_open_max_calls:
            self._half_open_calls += 1
            return True

        self._total_blocked += 1
        return False

    def record_success(self) -> None:
        """Record a successful operation."""
        self._success_count += 1
        self._last_success_time = datetime.now(UTC)

        if self._state == CircuitState.HALF_OPEN:
            # Success in half-open: close the circuit
            self._transition_to(CircuitState.CLOSED)
            self._failure_count = 0

    def record_failure(self) -> None:
        """Record a failed operation."""
        self._failure_count += 1
        self._last_failure_time = datetime.now(UTC)

        if self._state == CircuitState.HALF_OPEN:
            # Failure in half-open: reopen circuit
            self._transition_to(CircuitState.OPEN)
        elif self._state == CircuitState.CLOSED:
            # Check if we should open
            if self._failure_count >= self.threshold:
                self._transition_to(CircuitState.OPEN)

    def reset(self) -> None:
        """Reset the circuit breaker to closed state."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0
        self._last_failure_time = None
        self._last_success_time = None
        self._last_state_change = datetime.now(UTC)
        logger.info("Circuit breaker '%s' manually reset", self.name)

    def get_stats(self) -> CircuitBreakerStats:
        """Get circuit breaker statistics.

        Returns:
            CircuitBreakerStats with current metrics.
        """
        return CircuitBreakerStats(
            state=self._state,
            failure_count=self._failure_count,
            success_count=self._success_count,
            last_failure_time=self._last_failure_time,
            last_success_time=self._last_success_time,
            last_state_change=self._last_state_change,
            total_blocked=self._total_blocked,
            total_requests=self._total_requests,
        )

    def protect(
        self,
        fallback: Callable[..., T] | T | None = None,
    ) -> Callable[[Callable[..., T]], Callable[..., T]]:
        """Decorator to protect a function with the circuit breaker.

        Args:
            fallback: Fallback value or function if circuit is open.

        Returns:
            Decorator function.

        Example:
            @breaker.protect(fallback=None)
            async def get_from_cache(key: str):
                return await cache.get(key)
        """

        def decorator(func: Callable[..., T]) -> Callable[..., T]:
            async def async_wrapper(*args: Any, **kwargs: Any) -> T:
                if not self.can_execute():
                    if callable(fallback):
                        return fallback(*args, **kwargs)
                    return fallback  # type: ignore

                try:
                    result = await func(*args, **kwargs)
                    self.record_success()
                    return result
                except Exception:
                    self.record_failure()
                    if callable(fallback):
                        return fallback(*args, **kwargs)
                    return fallback  # type: ignore

            def sync_wrapper(*args: Any, **kwargs: Any) -> T:
                if not self.can_execute():
                    if callable(fallback):
                        return fallback(*args, **kwargs)
                    return fallback  # type: ignore

                try:
                    result = func(*args, **kwargs)
                    self.record_success()
                    return result
                except Exception:
                    self.record_failure()
                    if callable(fallback):
                        return fallback(*args, **kwargs)
                    return fallback  # type: ignore

            if asyncio.iscoroutinefunction(func):
                return async_wrapper  # type: ignore
            return sync_wrapper  # type: ignore

        return decorator


class CircuitBreakerRegistry:
    """Registry for managing multiple circuit breakers.

    Example:
        registry = CircuitBreakerRegistry()
        cache_breaker = registry.get_or_create("cache", threshold=5)
        db_breaker = registry.get_or_create("database", threshold=3)
    """

    def __init__(self) -> None:
        """Initialize the registry."""
        self._breakers: dict[str, CircuitBreaker] = {}
        self._lock = asyncio.Lock()

    def get_or_create(
        self,
        name: str,
        threshold: int = 5,
        timeout: int = 30,
    ) -> CircuitBreaker:
        """Get or create a circuit breaker.

        Args:
            name: Breaker name.
            threshold: Failure threshold.
            timeout: Timeout in seconds.

        Returns:
            CircuitBreaker instance.
        """
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(
                name=name,
                threshold=threshold,
                timeout=timeout,
            )
        return self._breakers[name]

    def get(self, name: str) -> CircuitBreaker | None:
        """Get a circuit breaker by name.

        Args:
            name: Breaker name.

        Returns:
            CircuitBreaker or None.
        """
        return self._breakers.get(name)

    def get_all_stats(self) -> dict[str, CircuitBreakerStats]:
        """Get stats for all circuit breakers.

        Returns:
            Dictionary of name to stats.
        """
        return {name: breaker.get_stats() for name, breaker in self._breakers.items()}

    def reset_all(self) -> None:
        """Reset all circuit breakers."""
        for breaker in self._breakers.values():
            breaker.reset()


# Global registry
_circuit_registry = CircuitBreakerRegistry()


def get_circuit_breaker(
    name: str = "search_cache",
    threshold: int = 5,
    timeout: int = 30,
) -> CircuitBreaker:
    """Get or create a circuit breaker from the global registry.

    Args:
        name: Breaker name.
        threshold: Failure threshold.
        timeout: Timeout in seconds.

    Returns:
        CircuitBreaker instance.
    """
    return _circuit_registry.get_or_create(name, threshold, timeout)


def get_circuit_stats() -> dict[str, CircuitBreakerStats]:
    """Get stats for all circuit breakers.

    Returns:
        Dictionary of name to stats.
    """
    return _circuit_registry.get_all_stats()


__all__ = [
    "CircuitBreaker",
    "CircuitBreakerRegistry",
    "CircuitBreakerStats",
    "CircuitState",
    "get_circuit_breaker",
    "get_circuit_stats",
]
