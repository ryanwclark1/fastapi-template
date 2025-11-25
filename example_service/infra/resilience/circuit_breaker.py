"""Circuit breaker pattern implementation for resilient external service calls."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from enum import Enum
from functools import wraps
from typing import Any, TypeVar

from example_service.core.exceptions import CircuitBreakerOpenException
from example_service.infra.metrics.tracking import (
    track_circuit_breaker_failure,
    track_circuit_breaker_state_change,
    track_circuit_breaker_success,
    update_circuit_breaker_state,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(str, Enum):
    """Circuit breaker states.

    - CLOSED: Normal operation, requests are allowed
    - OPEN: Circuit is open, requests fail immediately
    - HALF_OPEN: Testing if service has recovered
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Circuit breaker for protecting against cascading failures.

    The circuit breaker pattern prevents an application from repeatedly
    attempting an operation that is likely to fail, allowing it to continue
    without waiting for the fault to be fixed or wasting resources.

    States:
        - CLOSED: Normal operation, all requests allowed
        - OPEN: Failures exceeded threshold, requests fail fast
        - HALF_OPEN: Testing recovery, limited requests allowed

    Attributes:
        name: Identifier for this circuit breaker.
        failure_threshold: Number of failures before opening circuit.
        recovery_timeout: Seconds to wait before attempting recovery.
        expected_exception: Exception type that should trigger the circuit.
        success_threshold: Successful calls needed in HALF_OPEN to close circuit.

    Example:
            # Create circuit breaker
        breaker = CircuitBreaker(
            name="auth_service",
            failure_threshold=5,
            recovery_timeout=60,
            expected_exception=httpx.HTTPError
        )

        # Use as decorator
        @breaker
        async def call_auth_service():
            return await httpx.get("https://auth.example.com/verify")

        # Or use as context manager
        async with breaker:
            result = await call_auth_service()
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        expected_exception: type[Exception] = Exception,
        success_threshold: int = 2,
        half_open_max_calls: int = 1,
    ) -> None:
        """Initialize circuit breaker.

        Args:
            name: Identifier for this circuit breaker.
            failure_threshold: Number of consecutive failures before opening.
            recovery_timeout: Seconds to wait in OPEN state before HALF_OPEN.
            expected_exception: Exception type(s) that trigger the circuit.
            success_threshold: Successes needed in HALF_OPEN to close circuit.
            half_open_max_calls: Max concurrent calls allowed in HALF_OPEN state.
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.success_threshold = success_threshold
        self.half_open_max_calls = half_open_max_calls

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float | None = None
        self._half_open_calls = 0
        self._lock = asyncio.Lock()

        # Initialize metrics
        update_circuit_breaker_state(self.name, self._state.value)

        logger.info(
            f"Circuit breaker '{name}' initialized",
            extra={
                "failure_threshold": failure_threshold,
                "recovery_timeout": recovery_timeout,
            },
        )

    @property
    def state(self) -> CircuitState:
        """Get current circuit state.

        Automatically transitions from OPEN to HALF_OPEN if recovery
        timeout has elapsed.

        Returns:
            Current circuit state.
        """
        if (
            self._state == CircuitState.OPEN
            and self._last_failure_time is not None
            and time.time() - self._last_failure_time >= self.recovery_timeout
        ):
            logger.info(
                f"Circuit breaker '{self.name}' transitioning to HALF_OPEN",
                extra={"recovery_timeout": self.recovery_timeout},
            )
            old_state = self._state.value
            self._state = CircuitState.HALF_OPEN
            self._half_open_calls = 0

            # Track state change
            track_circuit_breaker_state_change(self.name, old_state, self._state.value)
            update_circuit_breaker_state(self.name, self._state.value)

        return self._state

    @property
    def is_closed(self) -> bool:
        """Check if circuit is closed (normal operation)."""
        return self.state == CircuitState.CLOSED

    @property
    def is_open(self) -> bool:
        """Check if circuit is open (failing fast)."""
        return self.state == CircuitState.OPEN

    @property
    def is_half_open(self) -> bool:
        """Check if circuit is half-open (testing recovery)."""
        return self.state == CircuitState.HALF_OPEN

    async def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Execute function with circuit breaker protection.

        Args:
            func: The async function to call.
            *args: Positional arguments for the function.
            **kwargs: Keyword arguments for the function.

        Returns:
            Result of the function call.

        Raises:
            CircuitBreakerOpenException: If circuit is open.
            Exception: Any exception from the function call.
        """
        async with self._lock:
            current_state = self.state

            if current_state == CircuitState.OPEN:
                raise CircuitBreakerOpenException(
                    detail=f"Circuit breaker '{self.name}' is open",
                    extra={
                        "service": self.name,
                        "failures": self._failure_count,
                        "retry_after": int(
                            self.recovery_timeout - (time.time() - (self._last_failure_time or 0))
                        ),
                    },
                )

            if (
                current_state == CircuitState.HALF_OPEN
                and self._half_open_calls >= self.half_open_max_calls
            ):
                raise CircuitBreakerOpenException(
                    detail=f"Circuit breaker '{self.name}' is half-open with max calls reached",
                    extra={
                        "service": self.name,
                        "state": "half_open",
                        "max_calls": self.half_open_max_calls,
                    },
                )

            if current_state == CircuitState.HALF_OPEN:
                self._half_open_calls += 1

        try:
            # Execute the function
            result = await func(*args, **kwargs)

            # Record success
            await self._on_success()

            return result

        except self.expected_exception as e:
            # Record failure
            await self._on_failure(e)
            raise

        except Exception as e:
            # Unexpected exceptions don't affect circuit state
            logger.warning(
                f"Circuit breaker '{self.name}' caught unexpected exception",
                extra={"exception_type": type(e).__name__},
            )
            raise

    async def _on_success(self) -> None:
        """Handle successful call."""
        async with self._lock:
            # Track success
            track_circuit_breaker_success(self.name)

            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                logger.info(
                    f"Circuit breaker '{self.name}' success in HALF_OPEN",
                    extra={
                        "success_count": self._success_count,
                        "success_threshold": self.success_threshold,
                    },
                )

                if self._success_count >= self.success_threshold:
                    self._close_circuit()
            elif self._state == CircuitState.CLOSED:
                # Reset failure count on success in CLOSED state
                if self._failure_count > 0:
                    logger.info(f"Circuit breaker '{self.name}' resetting failure count")
                    self._failure_count = 0

    async def _on_failure(self, exception: Exception) -> None:
        """Handle failed call.

        Args:
            exception: The exception that was raised.
        """
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            # Track failure
            track_circuit_breaker_failure(self.name)

            logger.warning(
                f"Circuit breaker '{self.name}' recorded failure",
                extra={
                    "failure_count": self._failure_count,
                    "failure_threshold": self.failure_threshold,
                    "exception_type": type(exception).__name__,
                },
            )

            if self._state == CircuitState.HALF_OPEN:
                # Any failure in HALF_OPEN reopens the circuit
                self._open_circuit()
            elif (
                self._state == CircuitState.CLOSED and self._failure_count >= self.failure_threshold
            ):
                # Threshold exceeded, open the circuit
                self._open_circuit()

    def _open_circuit(self) -> None:
        """Transition circuit to OPEN state."""
        old_state = self._state.value
        self._state = CircuitState.OPEN
        self._success_count = 0

        # Track state change
        track_circuit_breaker_state_change(self.name, old_state, self._state.value)
        update_circuit_breaker_state(self.name, self._state.value)

        logger.error(
            f"Circuit breaker '{self.name}' opened",
            extra={
                "failure_count": self._failure_count,
                "recovery_timeout": self.recovery_timeout,
            },
        )

    def _close_circuit(self) -> None:
        """Transition circuit to CLOSED state."""
        old_state = self._state.value
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0

        # Track state change
        track_circuit_breaker_state_change(self.name, old_state, self._state.value)
        update_circuit_breaker_state(self.name, self._state.value)

        logger.info(f"Circuit breaker '{self.name}' closed")

    async def reset(self) -> None:
        """Manually reset circuit breaker to CLOSED state."""
        async with self._lock:
            self._close_circuit()
            logger.info(f"Circuit breaker '{self.name}' manually reset")

    def __call__(self, func: Callable[..., T]) -> Callable[..., T]:
        """Use circuit breaker as a decorator.

        Args:
            func: The async function to wrap.

        Returns:
            Wrapped function with circuit breaker protection.

        Example:
                    breaker = CircuitBreaker("api")

            @breaker
            async def call_api():
                return await httpx.get("https://api.example.com")
        """

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            return await self.call(func, *args, **kwargs)

        return wrapper

    async def __aenter__(self) -> CircuitBreaker:
        """Enter circuit breaker context.

        Returns:
            This circuit breaker instance.

        Raises:
            CircuitBreakerOpenException: If circuit is open.
        """
        if self.is_open:
            raise CircuitBreakerOpenException(
                detail=f"Circuit breaker '{self.name}' is open",
                extra={
                    "service": self.name,
                    "failures": self._failure_count,
                    "retry_after": int(
                        self.recovery_timeout - (time.time() - (self._last_failure_time or 0))
                    ),
                },
            )
        return self

    async def __aexit__(self, exc_type: type, exc_val: Exception, exc_tb: Any) -> bool:
        """Exit circuit breaker context.

        Args:
            exc_type: Exception type if raised.
            exc_val: Exception value if raised.
            exc_tb: Exception traceback.

        Returns:
            False to propagate exceptions.
        """
        if exc_type is not None and issubclass(exc_type, self.expected_exception):
            await self._on_failure(exc_val)
        elif exc_type is None:
            await self._on_success()

        return False  # Don't suppress exceptions

    def get_stats(self) -> dict[str, Any]:
        """Get circuit breaker statistics.

        Returns:
            Dictionary containing circuit breaker stats.

        Example:
                    stats = breaker.get_stats()
            print(f"State: {stats['state']}, Failures: {stats['failure_count']}")
        """
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
            "last_failure_time": self._last_failure_time,
        }
