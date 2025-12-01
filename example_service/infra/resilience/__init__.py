"""Resilience patterns for handling failures gracefully.

This module provides production-ready resilience patterns to build robust,
fault-tolerant applications. It includes implementations for:

- Circuit Breaker: Prevents cascading failures by failing fast when services are unavailable
- (Future patterns: Retry, Bulkhead, Rate Limiter, Timeout, etc.)

The circuit breaker pattern is essential for building resilient microservices that can
gracefully handle external service failures without impacting overall system stability.

Example:
    >>> from example_service.infra.resilience import CircuitBreaker, CircuitOpenError
    >>>
    >>> # Create a circuit breaker for an external service
    >>> payment_breaker = CircuitBreaker(
    ...     name="payment_service",
    ...     failure_threshold=5,
    ...     recovery_timeout=60.0
    ... )
    >>>
    >>> # Use as decorator
    >>> @payment_breaker.protected
    ... async def charge_payment(amount: float):
    ...     return await payment_api.charge(amount)
    >>>
    >>> # Handle circuit open scenarios
    >>> try:
    ...     result = await charge_payment(100.0)
    ... except CircuitOpenError:
    ...     # Fallback logic (e.g., queue for later, use backup service)
    ...     logger.warning("Payment service unavailable, queuing transaction")

"""

from __future__ import annotations

from example_service.infra.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
)

__all__ = [
    "CircuitBreaker",
    "CircuitOpenError",
    "CircuitState",
]
