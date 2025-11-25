from __future__ import annotations

import random
from collections.abc import Callable


class RetryStrategy:
    def __init__(
        self,
        max_attempts: int = 3,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
        jitter_range: tuple[float, float] = (0.5, 1.5),
        exceptions: tuple[type[Exception], ...] = (Exception,),
        retry_if: Callable[[Exception], bool] | None = None,
        stop_after_delay: float | None = None,
    ) -> None:
        self.max_attempts = max_attempts
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.jitter_range = jitter_range
        self.exceptions = exceptions
        self.retry_if = retry_if
        self.stop_after_delay = stop_after_delay

    def should_retry(self, exception: Exception) -> bool:
        if self.retry_if is not None:
            return self.retry_if(exception)
        return isinstance(exception, self.exceptions)

    def calculate_delay(self, attempt: int) -> float:
        delay = self.initial_delay * (self.exponential_base**attempt)
        delay = min(delay, self.max_delay)
        if self.jitter:
            delay *= random.uniform(self.jitter_range[0], self.jitter_range[1])
        return delay
