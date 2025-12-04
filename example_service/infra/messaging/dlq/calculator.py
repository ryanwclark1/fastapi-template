"""Retry delay calculation for DLQ.

This module provides high-performance delay calculations for retry policies.
Each calculation method is O(1) complexity for optimal performance.

Performance Optimizations:
- Fibonacci uses Binet's closed-form formula: O(1) vs O(n) recursive
- All calculations are pure functions with no I/O
- Jitter uses Python's built-in random.uniform (C-level implementation)
"""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import DLQConfig, RetryPolicy


def calculate_delay(
    config: DLQConfig,
    attempt: int,
) -> int:
    """Calculate retry delay for a given attempt number.

    Supports all retry policies: IMMEDIATE, LINEAR, EXPONENTIAL, FIBONACCI.
    Applies jitter if enabled in config to prevent thundering herd.

    Args:
        config: DLQ configuration with policy and delay settings.
        attempt: Retry attempt number (0-based).

    Returns:
        Delay in milliseconds, capped by max_delay_ms.

    Example:
        from example_service.infra.messaging.dlq import DLQConfig, RetryPolicy

        config = DLQConfig(
            retry_policy=RetryPolicy.EXPONENTIAL,
            initial_delay_ms=1000,
            max_delay_ms=60000,
            jitter=True,
        )

        delay_1 = calculate_delay(config, 0)  # ~1000ms (with jitter: 500-1500ms)
        delay_2 = calculate_delay(config, 1)  # ~2000ms (with jitter: 1000-3000ms)
        delay_3 = calculate_delay(config, 2)  # ~4000ms (with jitter: 2000-6000ms)
    """

    # Calculate base delay based on policy
    base_delay = _calculate_base_delay(
        policy=config.retry_policy,
        initial_delay_ms=config.initial_delay_ms,
        multiplier=config.retry_multiplier,
        attempt=attempt,
    )

    # Cap at maximum delay
    capped_delay = min(base_delay, config.max_delay_ms)

    # Apply jitter if enabled
    if config.jitter:
        capped_delay = _apply_jitter(capped_delay, config.jitter_range)

    return int(capped_delay)


def _calculate_base_delay(
    policy: RetryPolicy,
    initial_delay_ms: int,
    multiplier: float,
    attempt: int,
) -> float:
    """Calculate base delay without jitter or capping.

    Args:
        policy: Retry policy to use.
        initial_delay_ms: Initial delay in milliseconds.
        multiplier: Backoff multiplier.
        attempt: Retry attempt number (0-based).

    Returns:
        Base delay in milliseconds (float for precision before rounding).
    """
    from .config import RetryPolicy

    match policy:
        case RetryPolicy.IMMEDIATE:
            return 0.0

        case RetryPolicy.LINEAR:
            # delay = initial * (attempt + 1)
            # attempt 0 -> 1x, attempt 1 -> 2x, attempt 2 -> 3x
            return float(initial_delay_ms * (attempt + 1))

        case RetryPolicy.EXPONENTIAL:
            # delay = initial * multiplier^attempt
            # attempt 0 -> 1x, attempt 1 -> 2x, attempt 2 -> 4x
            return initial_delay_ms * (multiplier**attempt)

        case RetryPolicy.FIBONACCI:
            # delay = initial * fib(attempt + 1)
            # attempt 0 -> 1x, attempt 1 -> 1x, attempt 2 -> 2x, attempt 3 -> 3x
            fib_num = _fibonacci_binet(attempt + 1)
            return float(initial_delay_ms * fib_num)

        case _:
            # Fallback to initial delay
            return float(initial_delay_ms)


def _fibonacci_binet(n: int) -> int:
    """Calculate nth Fibonacci number using Binet's formula.

    Uses the closed-form formula for O(1) complexity instead of
    O(n) iterative or O(2^n) recursive approaches.

    Binet's formula: F(n) = (phi^n - psi^n) / sqrt(5)
    where phi = (1 + sqrt(5)) / 2 (golden ratio)
    and psi = (1 - sqrt(5)) / 2

    Note: Floating point precision limits accuracy for n > 70,
    but retry attempts will never exceed that in practice.

    Args:
        n: Position in Fibonacci sequence (1-based).
           F(1) = 1, F(2) = 1, F(3) = 2, F(4) = 3, F(5) = 5, ...

    Returns:
        Fibonacci number at position n.

    Example:
        _fibonacci_binet(1)  # 1
        _fibonacci_binet(2)  # 1
        _fibonacci_binet(5)  # 5
        _fibonacci_binet(10) # 55
    """
    if n <= 0:
        return 0
    if n <= 2:
        return 1

    # Golden ratio and its conjugate
    sqrt5 = math.sqrt(5)
    phi = (1 + sqrt5) / 2
    psi = (1 - sqrt5) / 2

    # Binet's formula
    result = (phi**n - psi**n) / sqrt5
    return round(result)


def _apply_jitter(delay: float, jitter_range: tuple[float, float]) -> float:
    """Apply random jitter to delay to prevent thundering herd.

    Multiplies the delay by a random factor within the jitter range.
    This distributes retry attempts over time when multiple messages
    fail simultaneously.

    Args:
        delay: Base delay in milliseconds.
        jitter_range: Tuple of (min_multiplier, max_multiplier).

    Returns:
        Delay with jitter applied.

    Example:
        # With jitter_range=(0.5, 1.5):
        # - delay of 1000ms could become 500-1500ms
        _apply_jitter(1000.0, (0.5, 1.5))
    """
    min_jitter, max_jitter = jitter_range
    jitter_multiplier = random.uniform(min_jitter, max_jitter)
    return delay * jitter_multiplier


# ─────────────────────────────────────────────────────
# Alternative implementations for testing/benchmarking
# ─────────────────────────────────────────────────────


def _fibonacci_iterative(n: int) -> int:
    """Calculate nth Fibonacci number iteratively.

    O(n) complexity - kept for testing/comparison with Binet's formula.

    Args:
        n: Position in Fibonacci sequence (1-based).

    Returns:
        Fibonacci number at position n.
    """
    if n <= 0:
        return 0
    if n <= 2:
        return 1

    a, b = 1, 1
    for _ in range(n - 2):
        a, b = b, a + b
    return b


__all__ = ["calculate_delay"]
