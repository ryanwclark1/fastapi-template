"""Retry utilities - DEPRECATED.

This module is deprecated. Use example_service.utils.retry instead.

Migration guide:
- RetryConfig -> RetryStrategy (or use @retry decorator directly)
- with_retry -> retry
- retry_async -> Use @retry decorator instead
- exponential_backoff -> Handled internally by RetryStrategy
"""
from __future__ import annotations

import warnings
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any, TypeVar

from example_service.utils.retry import RetryStrategy, retry

warnings.warn(
    "example_service.infra.resilience.retry is deprecated. "
    "Use example_service.utils.retry instead.",
    DeprecationWarning,
    stacklevel=2,
)

T = TypeVar("T")


@dataclass
class RetryConfig:
    """DEPRECATED: Use RetryStrategy or @retry decorator instead."""

    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: int = 2
    jitter: bool = True
    jitter_ratio: float = 0.1
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,)


def exponential_backoff(
    attempt: int,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: int = 2,
    jitter: bool = True,
    jitter_ratio: float = 0.1,
) -> float:
    """DEPRECATED: Use RetryStrategy.calculate_delay() instead."""
    import random

    delay = min(base_delay * (exponential_base**attempt), max_delay)
    if jitter:
        jitter_amount = delay * jitter_ratio
        delay = delay + random.uniform(-jitter_amount, jitter_amount)
    return max(0, delay)


def with_retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: int = 2,
    jitter: bool = True,
    jitter_ratio: float = 0.1,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """DEPRECATED: Use @retry from example_service.utils.retry instead."""
    jitter_range = (1.0 - jitter_ratio, 1.0 + jitter_ratio) if jitter else (1.0, 1.0)
    return retry(
        max_attempts=max_attempts,
        initial_delay=base_delay,
        max_delay=max_delay,
        exponential_base=float(exponential_base),
        jitter=jitter,
        jitter_range=jitter_range,
        exceptions=retryable_exceptions,
    )


async def retry_async(
    func: Callable[..., T],
    *args: Any,
    config: RetryConfig | None = None,
    on_retry: Callable[[int, Exception], None] | None = None,
    **kwargs: Any,
) -> T:
    """DEPRECATED: Use @retry decorator instead."""
    config = config or RetryConfig()
    jitter_range = (
        (1.0 - config.jitter_ratio, 1.0 + config.jitter_ratio)
        if config.jitter
        else (1.0, 1.0)
    )

    @retry(
        max_attempts=config.max_attempts,
        initial_delay=config.base_delay,
        max_delay=config.max_delay,
        exponential_base=float(config.exponential_base),
        jitter=config.jitter,
        jitter_range=jitter_range,
        exceptions=config.retryable_exceptions,
        on_retry=lambda e, a: on_retry(a, e) if on_retry else None,
    )
    async def wrapped() -> T:
        return await func(*args, **kwargs)

    return await wrapped()


def combine_circuit_breaker_and_retry(
    circuit_breaker: Any,
    retry_config: RetryConfig | None = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Combine circuit breaker and retry patterns.

    Note: This function is maintained for backward compatibility.
    Consider using the decorators separately for more flexibility.
    """
    retry_config = retry_config or RetryConfig()

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            async def retry_wrapper() -> T:
                return await retry_async(func, *args, config=retry_config, **kwargs)

            return await circuit_breaker.call(retry_wrapper)

        return wrapper

    return decorator


__all__ = [
    "RetryConfig",
    "exponential_backoff",
    "retry_async",
    "with_retry",
    "combine_circuit_breaker_and_retry",
]
