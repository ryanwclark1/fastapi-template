"""Resilience patterns for handling failures gracefully."""
from __future__ import annotations

from example_service.infra.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
)

__all__ = [
    "CircuitBreaker",
    "CircuitState",
]
