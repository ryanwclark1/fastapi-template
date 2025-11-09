"""Retry and backoff utilities for resilient external service calls.

This module provides a custom retry mechanism similar to tenacity,
with support for exponential backoff, jitter, and configurable retry strategies.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RetryError(Exception):
    """Exception raised when all retry attempts are exhausted."""

    def __init__(self, last_exception: Exception, attempts: int) -> None:
        """Initialize retry error.

        Args:
            last_exception: The final exception that caused failure.
            attempts: Number of attempts made.
        """
        self.last_exception = last_exception
        self.attempts = attempts
        super().__init__(
            f"Failed after {attempts} attempts. Last error: {last_exception}"
        )


class RetryStrategy:
    """Base retry strategy class."""

    def __init__(
        self,
        max_attempts: int = 3,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
        exceptions: tuple[type[Exception], ...] = (Exception,),
    ) -> None:
        """Initialize retry strategy.

        Args:
            max_attempts: Maximum number of retry attempts.
            initial_delay: Initial delay in seconds before first retry.
            max_delay: Maximum delay in seconds between retries.
            exponential_base: Base for exponential backoff calculation.
            jitter: Whether to add random jitter to delays.
            exceptions: Tuple of exception types to retry on.
        """
        self.max_attempts = max_attempts
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.exceptions = exceptions

    def should_retry(self, exception: Exception) -> bool:
        """Check if exception should trigger a retry.

        Args:
            exception: The exception to check.

        Returns:
            True if should retry, False otherwise.
        """
        return isinstance(exception, self.exceptions)

    def calculate_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt number.

        Uses exponential backoff with optional jitter.

        Args:
            attempt: Current attempt number (0-indexed).

        Returns:
            Delay in seconds.
        """
        # Exponential backoff: initial_delay * (exponential_base ^ attempt)
        delay = min(
            self.initial_delay * (self.exponential_base**attempt), self.max_delay
        )

        # Add jitter to prevent thundering herd
        if self.jitter:
            delay = delay * (0.5 + random.random())  # Random between 50-150% of delay

        return delay


def retry(
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    on_retry: Callable[[Exception, int], None] | None = None,
) -> Callable:
    """Decorator for retrying async functions with exponential backoff.

    Args:
        max_attempts: Maximum number of retry attempts.
        initial_delay: Initial delay in seconds before first retry.
        max_delay: Maximum delay in seconds between retries.
        exponential_base: Base for exponential backoff calculation.
        jitter: Whether to add random jitter to delays.
        exceptions: Tuple of exception types to retry on.
        on_retry: Optional callback called on each retry with (exception, attempt).

    Returns:
        Decorator function.

    Example:
        ```python
        @retry(max_attempts=5, initial_delay=1.0, exceptions=(httpx.HTTPError,))
        async def fetch_data(url: str) -> dict:
            async with httpx.AsyncClient() as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.json()
        ```
    """
    strategy = RetryStrategy(
        max_attempts=max_attempts,
        initial_delay=initial_delay,
        max_delay=max_delay,
        exponential_base=exponential_base,
        jitter=jitter,
        exceptions=exceptions,
    )

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception: Exception | None = None

            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e

                    # Check if we should retry this exception
                    if not strategy.should_retry(e):
                        logger.warning(
                            f"Non-retryable exception in {func.__name__}: {e}",
                            extra={"function": func.__name__, "exception": str(e)},
                        )
                        raise

                    # Check if we've exhausted attempts
                    if attempt >= max_attempts - 1:
                        logger.error(
                            f"All retry attempts exhausted for {func.__name__}",
                            extra={
                                "function": func.__name__,
                                "attempts": max_attempts,
                                "last_exception": str(e),
                            },
                        )
                        raise RetryError(e, max_attempts) from e

                    # Calculate delay and wait
                    delay = strategy.calculate_delay(attempt)
                    logger.warning(
                        f"Retrying {func.__name__} after {delay:.2f}s (attempt {attempt + 1}/{max_attempts})",
                        extra={
                            "function": func.__name__,
                            "attempt": attempt + 1,
                            "max_attempts": max_attempts,
                            "delay": delay,
                            "exception": str(e),
                        },
                    )

                    # Call retry callback if provided
                    if on_retry:
                        on_retry(e, attempt + 1)

                    await asyncio.sleep(delay)

            # Should never reach here, but just in case
            if last_exception:
                raise RetryError(last_exception, max_attempts) from last_exception
            raise RuntimeError("Retry logic error: no exception captured")

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception: Exception | None = None

            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e

                    if not strategy.should_retry(e):
                        logger.warning(
                            f"Non-retryable exception in {func.__name__}: {e}",
                            extra={"function": func.__name__, "exception": str(e)},
                        )
                        raise

                    if attempt >= max_attempts - 1:
                        logger.error(
                            f"All retry attempts exhausted for {func.__name__}",
                            extra={
                                "function": func.__name__,
                                "attempts": max_attempts,
                                "last_exception": str(e),
                            },
                        )
                        raise RetryError(e, max_attempts) from e

                    delay = strategy.calculate_delay(attempt)
                    logger.warning(
                        f"Retrying {func.__name__} after {delay:.2f}s (attempt {attempt + 1}/{max_attempts})",
                        extra={
                            "function": func.__name__,
                            "attempt": attempt + 1,
                            "max_attempts": max_attempts,
                            "delay": delay,
                            "exception": str(e),
                        },
                    )

                    if on_retry:
                        on_retry(e, attempt + 1)

                    time.sleep(delay)

            if last_exception:
                raise RetryError(last_exception, max_attempts) from last_exception
            raise RuntimeError("Retry logic error: no exception captured")

        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore
        else:
            return sync_wrapper  # type: ignore

    return decorator


class CircuitBreaker:
    """Circuit breaker pattern for failing fast on repeated errors.

    Prevents cascading failures by stopping requests to failing services
    after a threshold is reached.

    States:
        - CLOSED: Normal operation, requests pass through
        - OPEN: Too many failures, requests fail immediately
        - HALF_OPEN: Testing if service recovered, limited requests allowed
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exception: type[Exception] = Exception,
    ) -> None:
        """Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit.
            recovery_timeout: Seconds to wait before attempting recovery.
            expected_exception: Exception type to track for failures.
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.failure_count = 0
        self.last_failure_time: float | None = None
        self.state = "CLOSED"

    def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Call function through circuit breaker.

        Args:
            func: Function to call.
            *args: Positional arguments for function.
            **kwargs: Keyword arguments for function.

        Returns:
            Function result.

        Raises:
            Exception: If circuit is open or function fails.
        """
        if self.state == "OPEN":
            if self._should_attempt_reset():
                self.state = "HALF_OPEN"
            else:
                raise Exception("Circuit breaker is OPEN")

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exception as e:
            self._on_failure()
            raise

    def _on_success(self) -> None:
        """Handle successful call."""
        self.failure_count = 0
        self.state = "CLOSED"

    def _on_failure(self) -> None:
        """Handle failed call."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logger.warning(
                f"Circuit breaker opened after {self.failure_count} failures",
                extra={"failure_count": self.failure_count, "state": self.state},
            )

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset.

        Returns:
            True if should attempt reset, False otherwise.
        """
        if self.last_failure_time is None:
            return False
        return (time.time() - self.last_failure_time) >= self.recovery_timeout
