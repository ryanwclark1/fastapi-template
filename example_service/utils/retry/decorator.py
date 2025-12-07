from __future__ import annotations

import asyncio
from functools import wraps
import logging
import time
from typing import TYPE_CHECKING, ParamSpec, TypeVar

from example_service.infra.metrics.tracking import (
    track_retry_attempt,
    track_retry_exhausted,
    track_retry_success,
)

from .exceptions import RetryError, RetryStatistics
from .strategies import RetryStrategy

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


def retry(
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    jitter_range: tuple[float, float] = (0.5, 1.5),
    exceptions: tuple[type[Exception], ...] = (Exception,),
    retry_if: Callable[[Exception], bool] | None = None,
    stop_after_delay: float | None = None,
    on_retry: Callable[[Exception, int], None] | None = None,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    strategy = RetryStrategy(
        max_attempts=max_attempts,
        initial_delay=initial_delay,
        max_delay=max_delay,
        exponential_base=exponential_base,
        jitter=jitter,
        jitter_range=jitter_range,
        exceptions=exceptions,
        retry_if=retry_if,
        stop_after_delay=stop_after_delay,
    )

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            statistics = RetryStatistics(start_time=time.monotonic())

            for attempt in range(max_attempts):
                try:
                    result = await func(*args, **kwargs)
                    # Track success after retries
                    if statistics.attempts > 0:
                        track_retry_success(func.__name__, statistics.attempts + 1)
                    return result
                except Exception as e:
                    if not strategy.should_retry(e):
                        logger.warning(
                            f"Non-retryable exception in {func.__name__}: {e}",
                            extra={"function": func.__name__, "exception": str(e)},
                        )
                        raise

                    elapsed = time.monotonic() - statistics.start_time
                    if stop_after_delay is not None and elapsed >= stop_after_delay:
                        statistics.end_time = time.monotonic()
                        raise RetryError(e, attempt + 1, statistics) from e

                    if attempt >= max_attempts - 1:
                        statistics.end_time = time.monotonic()
                        # Track retry exhaustion
                        track_retry_exhausted(func.__name__)
                        logger.error(
                            f"All retry attempts exhausted for {func.__name__}",
                            extra={
                                "function": func.__name__,
                                "attempts": attempt + 1,
                                "last_exception": str(e),
                                "total_delay": statistics.total_delay,
                                "duration": statistics.duration,
                            },
                        )
                        raise RetryError(e, attempt + 1, statistics) from e

                    delay = strategy.calculate_delay(attempt)
                    statistics.attempts += 1
                    statistics.total_delay += delay
                    statistics.exceptions.append(type(e).__name__)

                    # Track retry attempt
                    track_retry_attempt(func.__name__, attempt + 2)

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

                    await asyncio.sleep(delay)

            msg = "Retry logic error: exhausted all attempts"
            raise RuntimeError(msg)

        return async_wrapper

    return decorator
