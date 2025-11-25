"""Logging infrastructure.

Provides production-ready structured logging with:
- JSONL format for Loki/Elasticsearch ingestion
- Automatic context injection (request_id, user_id, etc.)
- QueueHandler + QueueListener for non-blocking I/O
- Per-handler log levels (console vs file)
- Lazy evaluation for expensive operations
- OpenTelemetry trace correlation

Basic usage:
    ```python
    # Automatic context injection (recommended)
    from example_service.infra.logging.context import set_log_context
    import logging

    logger = logging.getLogger(__name__)

    # Set context once, all logs include it
    set_log_context(request_id="abc-123", user_id=42)
    logger.info("Processing request")  # Automatically includes request_id and user_id

    # Lazy evaluation for expensive operations
    from example_service.infra.logging.lazy import get_lazy_logger

    lazy_logger = get_lazy_logger(__name__)
    lazy_logger.debug(lambda: f"Expensive: {compute_heavy_data()}")  # Only runs if DEBUG enabled
    ```
"""
from example_service.infra.logging.config import configure_logging
from example_service.infra.logging.context import (
    ContextBoundLogger,
    ContextInjectingFilter,
    clear_log_context,
    get_log_context,
    get_logger,
    set_log_context,
    update_log_context,
)
from example_service.infra.logging.formatters import JSONFormatter
from example_service.infra.logging.lazy import (
    LazyLoggerAdapter,
    LazyString,
    get_lazy_logger,
    lazy,
)
from example_service.infra.logging.sampling import (
    RateLimitFilter,
    SamplingFilter,
    create_sampling_config,
)

__all__ = [
    # Configuration
    "configure_logging",
    # Context management (recommended)
    "set_log_context",
    "get_log_context",
    "clear_log_context",
    "update_log_context",
    # Context-bound loggers
    "ContextBoundLogger",
    "get_logger",
    # Lazy evaluation
    "LazyLoggerAdapter",
    "LazyString",
    "get_lazy_logger",
    "lazy",
    # Formatters and filters
    "JSONFormatter",
    "ContextInjectingFilter",
    # Sampling and rate limiting
    "SamplingFilter",
    "RateLimitFilter",
    "create_sampling_config",
]
