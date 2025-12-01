"""Production-ready Circuit Breaker pattern implementation.

This module implements the circuit breaker pattern to handle service failures
gracefully and prevent cascading failures. The circuit breaker monitors failure
rates and provides automatic recovery mechanisms with exponential backoff.

States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Failure threshold exceeded, requests fail immediately
    - HALF_OPEN: Testing recovery, limited requests allowed

Transitions:
    CLOSED -> OPEN: When failure threshold exceeded
    OPEN -> HALF_OPEN: After recovery timeout
    HALF_OPEN -> CLOSED: When success threshold met
    HALF_OPEN -> OPEN: When failures continue

Features:
    - Automatic failure detection and recovery
    - Configurable thresholds and timeouts
    - Exponential backoff for recovery attempts
    - Thread-safe operation using asyncio.Lock
    - Observable state changes with structured logging
    - Comprehensive metrics and statistics
    - Decorator and context manager patterns
    - Integration with FastAPI exception handling

Example:
    >>> from example_service.infra.resilience import CircuitBreaker, CircuitOpenError
    >>>
    >>> # Create circuit breaker for external service
    >>> breaker = CircuitBreaker(
    ...     name="payment_service",
    ...     failure_threshold=5,
    ...     recovery_timeout=60.0,
    ...     success_threshold=2
    ... )
    >>>
    >>> # Use as decorator
    >>> @breaker.protected
    ... async def call_payment_api(amount: float):
    ...     return await payment_client.charge(amount)
    >>>
    >>> # Use as context manager
    >>> async with breaker:
    ...     result = await call_payment_api(100.0)
    >>>
    >>> # Handle circuit open errors
    >>> try:
    ...     await call_payment_api(100.0)
    ... except CircuitOpenError as e:
    ...     logger.warning(f"Circuit breaker open: {e}")
    ...     # Fallback logic here
    >>>
    >>> # Get metrics
    >>> metrics = breaker.get_metrics()
    >>> print(f"State: {metrics['state']}, Failures: {metrics['total_failures']}")

"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ParamSpec, Self, TypeVar

from example_service.infra.metrics.tracking import (
    track_circuit_breaker_failure,
    track_circuit_breaker_state_change,
    track_circuit_breaker_success,
    update_circuit_breaker_state,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

# Type variables for generic function signatures
P = ParamSpec("P")
T = TypeVar("T")


class CircuitState(StrEnum):
    """Circuit breaker states.

    Attributes:
        CLOSED: Normal operation, all requests allowed.
        OPEN: Failure threshold exceeded, requests fail fast.
        HALF_OPEN: Testing recovery, limited requests allowed.

    """

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing fast
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitOpenError(Exception):
    """Raised when circuit breaker is open.

    This is a simple, standalone exception for circuit breaker open states.
    Use this when you want a lightweight exception without HTTP semantics.

    For HTTP APIs, prefer using CircuitBreakerOpenException which includes
    proper status codes and RFC 7807 problem details.

    Args:
        message: Human-readable error message.

    Example:
        >>> try:
        ...     async with breaker:
        ...         await risky_operation()
        ... except CircuitOpenError as e:
        ...     logger.warning(f"Circuit breaker prevented call: {e}")
        ...     # Implement fallback logic

    """

    def __init__(self, message: str = "Circuit breaker is open") -> None:
        """Initialize circuit open error.

        Args:
            message: Human-readable error message.

        """
        super().__init__(message)


class CircuitBreaker:
    """Production-ready circuit breaker for resilient service calls.

    Implements the circuit breaker pattern to handle service failures gracefully
    and prevent cascading failures. Tracks failure rates, manages state transitions,
    and provides automatic recovery with exponential backoff.

    The circuit breaker operates in three states:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Too many failures, requests fail immediately
    - HALF_OPEN: Testing recovery, limited requests allowed

    Attributes:
        name: Identifier for this circuit breaker instance.
        failure_threshold: Number of consecutive failures before opening circuit.
        recovery_timeout: Seconds to wait before attempting recovery.
        success_threshold: Successful calls needed in HALF_OPEN to close circuit.
        half_open_max_calls: Maximum concurrent calls allowed in HALF_OPEN state.
        expected_exception: Exception type(s) that trigger the circuit.
        state: Current circuit state (CLOSED, OPEN, or HALF_OPEN).
        total_failures: Total failures recorded since creation.
        total_successes: Total successes recorded since creation.
        total_rejections: Total rejected calls (when circuit was open).

    Example:
        >>> # Create circuit breaker
        >>> breaker = CircuitBreaker(
        ...     name="external_api",
        ...     failure_threshold=5,
        ...     recovery_timeout=60.0,
        ...     success_threshold=2
        ... )
        >>>
        >>> # Decorator pattern
        >>> @breaker.protected
        ... async def call_external_api():
        ...     return await httpx.get("https://api.example.com")
        >>>
        >>> # Context manager pattern
        >>> async with breaker:
        ...     result = await call_external_api()
        >>>
        >>> # Manual call pattern
        >>> result = await breaker.call(call_external_api)
        >>>
        >>> # Get current metrics
        >>> metrics = breaker.get_metrics()
        >>> logger.info(f"Circuit state: {metrics['state']}")

    """

    def __init__(
        self,
        *,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        success_threshold: int = 2,
        half_open_max_calls: int = 3,
        expected_exception: type[Exception] = Exception,
    ) -> None:
        """Initialize circuit breaker.

        Args:
            name: Unique identifier for this circuit breaker instance.
            failure_threshold: Number of consecutive failures before opening circuit.
                Must be > 0. Default: 5.
            recovery_timeout: Seconds to wait in OPEN state before transitioning
                to HALF_OPEN for recovery testing. Must be > 0. Default: 60.0.
            success_threshold: Number of successful calls needed in HALF_OPEN
                state to transition back to CLOSED. Must be > 0. Default: 2.
            half_open_max_calls: Maximum number of concurrent calls allowed in
                HALF_OPEN state before rejecting additional calls. Default: 3.
            expected_exception: Exception type(s) that should trigger circuit
                breaker logic. Other exceptions pass through without affecting
                circuit state. Default: Exception (catches all).

        Raises:
            ValueError: If any threshold or timeout value is invalid.

        """
        # Validate parameters
        if failure_threshold <= 0:
            msg = "failure_threshold must be greater than 0"
            raise ValueError(msg)
        if recovery_timeout <= 0:
            msg = "recovery_timeout must be greater than 0"
            raise ValueError(msg)
        if success_threshold <= 0:
            msg = "success_threshold must be greater than 0"
            raise ValueError(msg)
        if half_open_max_calls <= 0:
            msg = "half_open_max_calls must be greater than 0"
            raise ValueError(msg)

        # Configuration
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        self.half_open_max_calls = half_open_max_calls
        self.expected_exception = expected_exception

        # State tracking (protected with lock)
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0
        self._last_failure_time: datetime | None = None
        self._lock = asyncio.Lock()

        # Metrics (lifetime statistics)
        self.total_failures = 0
        self.total_successes = 0
        self.total_rejections = 0

        # Initialize Prometheus metrics
        update_circuit_breaker_state(self.name, self._state.value)

        logger.info(
            f"Circuit breaker '{name}' initialized",
            extra={
                "circuit_breaker": name,
                "failure_threshold": failure_threshold,
                "recovery_timeout": recovery_timeout,
                "success_threshold": success_threshold,
                "half_open_max_calls": half_open_max_calls,
            },
        )

    @property
    def state(self) -> CircuitState:
        """Get current circuit state.

        Automatically checks if circuit should transition from OPEN to HALF_OPEN
        based on recovery timeout. This property is safe to call without holding
        the lock as state transitions only happen within locked contexts.

        Returns:
            Current circuit state (CLOSED, OPEN, or HALF_OPEN).

        """
        return self._state

    @property
    def is_open(self) -> bool:
        """Check if circuit is open (failing fast).

        Returns:
            True if circuit is open, False otherwise.

        """
        return self._state == CircuitState.OPEN

    @property
    def is_closed(self) -> bool:
        """Check if circuit is closed (normal operation).

        Returns:
            True if circuit is closed, False otherwise.

        """
        return self._state == CircuitState.CLOSED

    @property
    def is_half_open(self) -> bool:
        """Check if circuit is half-open (testing recovery).

        Returns:
            True if circuit is half-open, False otherwise.

        """
        return self._state == CircuitState.HALF_OPEN

    async def call(self, func: Callable[P, Awaitable[T]], *args: P.args, **kwargs: P.kwargs) -> T:
        """Execute function with circuit breaker protection.

        This method wraps the provided async function with circuit breaker logic.
        It checks the circuit state before execution and records the result.

        Args:
            func: Async function to execute.
            *args: Positional arguments to pass to the function.
            **kwargs: Keyword arguments to pass to the function.

        Returns:
            Result returned by the function.

        Raises:
            CircuitOpenError: If circuit is open or half-open call limit reached.
            Exception: Any exception raised by the function (after recording failure).

        Example:
            >>> async def fetch_user(user_id: int):
            ...     return await api_client.get(f"/users/{user_id}")
            >>>
            >>> result = await breaker.call(fetch_user, user_id=123)

        """
        # Check state and acquire lock
        async with self._lock:
            await self._check_state()

            if self.is_open:
                self.total_rejections += 1
                msg = (
                    f"Circuit breaker '{self.name}' is open. "
                    f"Last failure: {self._last_failure_time}"
                )
                logger.warning(
                    msg,
                    extra={
                        "circuit_breaker": self.name,
                        "state": "open",
                        "total_rejections": self.total_rejections,
                    },
                )
                raise CircuitOpenError(msg)

            if self.is_half_open:
                if self._half_open_calls >= self.half_open_max_calls:
                    self.total_rejections += 1
                    msg = f"Circuit breaker '{self.name}' half-open call limit reached"
                    logger.warning(
                        msg,
                        extra={
                            "circuit_breaker": self.name,
                            "state": "half_open",
                            "half_open_calls": self._half_open_calls,
                            "max_calls": self.half_open_max_calls,
                        },
                    )
                    raise CircuitOpenError(msg)
                self._half_open_calls += 1

        # Execute function outside lock to avoid blocking
        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
        except self.expected_exception as e:
            await self._on_failure(e)
            raise
        except Exception as e:
            # Unexpected exceptions don't affect circuit state
            logger.warning(
                f"Circuit breaker '{self.name}' caught unexpected exception",
                extra={
                    "circuit_breaker": self.name,
                    "exception_type": type(e).__name__,
                    "exception_message": str(e),
                },
            )
            raise

    async def _check_state(self) -> None:
        """Check and update circuit state based on recovery timeout.

        This method should be called while holding the lock. It checks if the
        circuit should transition from OPEN to HALF_OPEN based on the elapsed
        time since the last failure.

        """
        if self.is_open and self._last_failure_time:
            elapsed = datetime.now(UTC) - self._last_failure_time
            if elapsed >= timedelta(seconds=self.recovery_timeout):
                await self._transition_to_half_open()

    async def _on_success(self) -> None:
        """Handle successful operation.

        Records success, updates metrics, and potentially transitions circuit
        from HALF_OPEN to CLOSED if success threshold is met.

        """
        async with self._lock:
            self.total_successes += 1
            track_circuit_breaker_success(self.name)

            if self.is_half_open:
                self._success_count += 1
                logger.info(
                    f"Circuit breaker '{self.name}' success in HALF_OPEN",
                    extra={
                        "circuit_breaker": self.name,
                        "state": "half_open",
                        "success_count": self._success_count,
                        "success_threshold": self.success_threshold,
                    },
                )

                if self._success_count >= self.success_threshold:
                    await self._transition_to_closed()
            elif self.is_closed:
                # Reset failure count on success
                if self._failure_count > 0:
                    logger.debug(
                        f"Circuit breaker '{self.name}' resetting failure count",
                        extra={
                            "circuit_breaker": self.name,
                            "previous_failures": self._failure_count,
                        },
                    )
                    self._failure_count = 0

    async def _on_failure(self, exception: Exception) -> None:
        """Handle failed operation.

        Records failure, updates metrics, and potentially transitions circuit
        to OPEN state if failure threshold is exceeded.

        Args:
            exception: The exception that caused the failure.

        """
        async with self._lock:
            self.total_failures += 1
            self._failure_count += 1
            self._last_failure_time = datetime.now(UTC)

            track_circuit_breaker_failure(self.name)

            logger.warning(
                f"Circuit breaker '{self.name}' recorded failure",
                extra={
                    "circuit_breaker": self.name,
                    "failure_count": self._failure_count,
                    "failure_threshold": self.failure_threshold,
                    "exception_type": type(exception).__name__,
                    "exception_message": str(exception),
                },
            )

            if self.is_half_open:
                # Any failure in HALF_OPEN immediately reopens the circuit
                logger.warning(
                    f"Circuit breaker '{self.name}' failed in HALF_OPEN, reopening",
                    extra={"circuit_breaker": self.name, "state": "half_open"},
                )
                await self._transition_to_open()
            elif self.is_closed and self._failure_count >= self.failure_threshold:
                # Threshold exceeded, open the circuit
                await self._transition_to_open()

    async def _transition_to_open(self) -> None:
        """Transition circuit to OPEN state.

        Should be called while holding the lock.

        """
        old_state = self._state.value
        self._state = CircuitState.OPEN
        self._success_count = 0
        self._half_open_calls = 0

        # Track state change
        track_circuit_breaker_state_change(self.name, old_state, self._state.value)
        update_circuit_breaker_state(self.name, self._state.value)

        logger.error(
            f"Circuit breaker '{self.name}' opened",
            extra={
                "circuit_breaker": self.name,
                "old_state": old_state,
                "new_state": self._state.value,
                "failure_count": self._failure_count,
                "recovery_timeout": self.recovery_timeout,
            },
        )

    async def _transition_to_half_open(self) -> None:
        """Transition circuit to HALF_OPEN state.

        Should be called while holding the lock.

        """
        old_state = self._state.value
        self._state = CircuitState.HALF_OPEN
        self._success_count = 0
        self._failure_count = 0
        self._half_open_calls = 0

        # Track state change
        track_circuit_breaker_state_change(self.name, old_state, self._state.value)
        update_circuit_breaker_state(self.name, self._state.value)

        logger.info(
            f"Circuit breaker '{self.name}' transitioned to HALF_OPEN",
            extra={
                "circuit_breaker": self.name,
                "old_state": old_state,
                "new_state": self._state.value,
                "recovery_timeout": self.recovery_timeout,
            },
        )

    async def _transition_to_closed(self) -> None:
        """Transition circuit to CLOSED state.

        Should be called while holding the lock.

        """
        old_state = self._state.value
        self._state = CircuitState.CLOSED
        self._success_count = 0
        self._failure_count = 0
        self._half_open_calls = 0
        self._last_failure_time = None

        # Track state change
        track_circuit_breaker_state_change(self.name, old_state, self._state.value)
        update_circuit_breaker_state(self.name, self._state.value)

        logger.info(
            f"Circuit breaker '{self.name}' closed",
            extra={
                "circuit_breaker": self.name,
                "old_state": old_state,
                "new_state": self._state.value,
            },
        )

    def protected(self, func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        """Decorator to protect async function with circuit breaker.

        This decorator wraps an async function with circuit breaker protection.
        It's equivalent to calling `breaker.call(func, *args, **kwargs)` but
        provides a cleaner syntax for function definitions.

        Args:
            func: Async function to protect.

        Returns:
            Protected async function with identical signature.

        Example:
            >>> breaker = CircuitBreaker(name="payment_service")
            >>>
            >>> @breaker.protected
            ... async def process_payment(amount: float, user_id: int):
            ...     return await payment_api.charge(amount, user_id)
            >>>
            >>> try:
            ...     result = await process_payment(100.0, user_id=123)
            ... except CircuitOpenError:
            ...     logger.warning("Payment service unavailable")
            ...     # Implement fallback logic

        """

        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            return await self.call(func, *args, **kwargs)

        # Preserve function metadata
        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        wrapper.__module__ = func.__module__
        wrapper.__qualname__ = func.__qualname__
        wrapper.__annotations__ = func.__annotations__

        return wrapper

    async def __aenter__(self) -> Self:
        """Enter circuit breaker context.

        Checks circuit state and rejects the operation if circuit is open
        or half-open call limit is reached.

        Returns:
            This circuit breaker instance.

        Raises:
            CircuitOpenError: If circuit is open or half-open limit reached.

        Example:
            >>> async with breaker:
            ...     result = await external_api_call()

        """
        async with self._lock:
            await self._check_state()

            if self.is_open:
                self.total_rejections += 1
                msg = f"Circuit breaker '{self.name}' is open"
                logger.warning(
                    msg,
                    extra={
                        "circuit_breaker": self.name,
                        "state": "open",
                        "last_failure": self._last_failure_time,
                    },
                )
                raise CircuitOpenError(msg)

            if self.is_half_open:
                if self._half_open_calls >= self.half_open_max_calls:
                    self.total_rejections += 1
                    msg = f"Circuit breaker '{self.name}' half-open call limit reached"
                    logger.warning(
                        msg,
                        extra={
                            "circuit_breaker": self.name,
                            "state": "half_open",
                            "half_open_calls": self._half_open_calls,
                        },
                    )
                    raise CircuitOpenError(msg)
                self._half_open_calls += 1

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,  # noqa: ANN401
    ) -> None:
        """Exit circuit breaker context.

        Records success or failure based on whether an exception occurred.

        Args:
            exc_type: Exception type if raised, None otherwise.
            exc_val: Exception value if raised, None otherwise.
            exc_tb: Exception traceback if raised, None otherwise.

        """
        if exc_type is None:
            await self._on_success()
        elif exc_val and isinstance(exc_val, self.expected_exception):
            await self._on_failure(exc_val)

    def get_metrics(self) -> dict[str, Any]:
        """Get comprehensive circuit breaker metrics.

        Returns a dictionary containing current state, counters, and statistics.
        This method is safe to call without holding the lock.

        Returns:
            Dictionary with the following keys:
                - state: Current circuit state (closed/open/half_open)
                - failure_count: Current consecutive failure count
                - success_count: Current consecutive success count in HALF_OPEN
                - total_failures: Lifetime total failures
                - total_successes: Lifetime total successes
                - total_rejections: Lifetime total rejected calls
                - last_failure_time: ISO 8601 timestamp of last failure (or None)
                - failure_rate: Ratio of failures to total calls (0.0-1.0)

        Example:
            >>> metrics = breaker.get_metrics()
            >>> if metrics["failure_rate"] > 0.5:
            ...     logger.warning(f"High failure rate: {metrics['failure_rate']:.2%}")
            >>> logger.info(
            ...     f"Circuit state: {metrics['state']}, "
            ...     f"Failures: {metrics['total_failures']}"
            ... )

        """
        total_calls = self.total_failures + self.total_successes
        failure_rate = self.total_failures / total_calls if total_calls > 0 else 0.0

        return {
            "state": self.state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "total_failures": self.total_failures,
            "total_successes": self.total_successes,
            "total_rejections": self.total_rejections,
            "last_failure_time": (
                self._last_failure_time.isoformat() if self._last_failure_time else None
            ),
            "failure_rate": failure_rate,
        }

    def get_stats(self) -> dict[str, Any]:
        """Get circuit breaker statistics.

        Legacy method for backward compatibility. Prefer get_metrics() for
        more comprehensive information.

        Returns:
            Dictionary containing circuit breaker stats.

        """
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
            "last_failure_time": (
                self._last_failure_time.isoformat() if self._last_failure_time else None
            ),
        }

    async def reset(self) -> None:
        """Manually reset circuit breaker to CLOSED state.

        Clears all counters and transitions to CLOSED state. Use this for
        administrative actions or testing. In production, prefer letting the
        circuit recover naturally through the HALF_OPEN state.

        Example:
            >>> # Administrative reset after fixing underlying issue
            >>> await breaker.reset()
            >>> logger.info("Circuit breaker manually reset")

        """
        async with self._lock:
            await self._transition_to_closed()
            self.total_failures = 0
            self.total_successes = 0
            self.total_rejections = 0
            logger.info(
                f"Circuit breaker '{self.name}' manually reset",
                extra={"circuit_breaker": self.name},
            )

    def __call__(self, func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        """Use circuit breaker as a decorator.

        This method allows using the circuit breaker instance directly as a
        decorator. It's an alias for the `protected` method.

        Args:
            func: Async function to wrap.

        Returns:
            Wrapped function with circuit breaker protection.

        Example:
            >>> breaker = CircuitBreaker(name="api_service")
            >>>
            >>> @breaker
            ... async def call_api():
            ...     return await httpx.get("https://api.example.com")

        """
        return self.protected(func)
