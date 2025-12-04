"""Dead Letter Queue (DLQ) support for messaging.

This package provides comprehensive DLQ functionality including:
- Configuration models for DLQ behavior
- Retry policies with exponential, fibonacci, and linear backoff
- Message tracking and retry state management
- Poison message detection
- TTL-based message expiration
- Prometheus metrics for observability
- FastStream middleware integration

The DLQ pattern ensures message durability and prevents message loss when
consumers fail to process messages due to transient errors (timeouts, service
unavailability) or permanent errors (validation failures, business logic errors).

Example:
    from example_service.infra.messaging.dlq import DLQConfig, RetryPolicy

    dlq_config = DLQConfig(
        enabled=True,
        max_retries=5,
        retry_policy=RetryPolicy.EXPONENTIAL,
    )

    # Create middleware for FastStream
    from example_service.infra.messaging.dlq import create_dlq_middleware, PoisonMessageDetector

    poison_detector = PoisonMessageDetector(threshold=3)
    middleware = create_dlq_middleware(broker, dlq_config, poison_detector)
"""

from __future__ import annotations

from .alerting import (
    AlertChannel,
    AlertConfig,
    AlertSeverity,
    DLQAlert,
    DLQAlerter,
    get_dlq_alerter,
)
from .calculator import calculate_delay
from .config import DLQConfig, RetryPolicy
from .exceptions import (
    is_non_retryable_exception,
    register_non_retryable,
)
from .headers import RetryState
from .middleware import DLQMiddleware, create_dlq_middleware
from .poison import PoisonMessageDetector
from .ttl import is_message_expired

__all__ = [
    # Alerting
    "AlertChannel",
    "AlertConfig",
    "AlertSeverity",
    "DLQAlert",
    "DLQAlerter",
    # Config
    "DLQConfig",
    # Middleware
    "DLQMiddleware",
    # Poison detection
    "PoisonMessageDetector",
    "RetryPolicy",
    # Headers
    "RetryState",
    # Calculator
    "calculate_delay",
    "create_dlq_middleware",
    "get_dlq_alerter",
    # TTL
    "is_message_expired",
    # Exceptions
    "is_non_retryable_exception",
    "register_non_retryable",
]
