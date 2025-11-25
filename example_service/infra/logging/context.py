"""Context management for structured logging.

Provides automatic context injection into log records using contextvars,
enabling request IDs, user IDs, and other contextual information to be
automatically included in all log messages without explicit passing.

This approach is:
- Async-safe: Works correctly across async/await boundaries
- Thread-safe: Each async task gets its own context
- Implicit: No need to modify existing logging calls
- Compatible: Works with standard Python logging
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any

# Global context variable for log context
# Each async task gets its own copy automatically
_log_context: ContextVar[dict[str, Any]] = ContextVar("log_context", default={})


def set_log_context(**kwargs: Any) -> None:
    """Set logging context for current async task/thread.

    All subsequent log calls in this context will automatically include
    these fields in the log record's extra dict.

    Args:
        **kwargs: Key-value pairs to add to logging context.
            Common examples: request_id, user_id, trace_id, session_id

    Example:
        ```python
        # In middleware
        set_log_context(request_id="abc-123", path="/api/users")

        # In auth dependency
        set_log_context(user_id=42, username="alice")

        # All subsequent logs automatically include this context:
        logger.info("Processing request")  # Includes request_id, user_id, etc.
        ```
    """
    current = _log_context.get().copy()
    current.update(kwargs)
    _log_context.set(current)


def get_log_context() -> dict[str, Any]:
    """Get current logging context.

    Returns:
        Dictionary of current context key-value pairs.

    Example:
        ```python
        context = get_log_context()
        print(context)  # {'request_id': 'abc-123', 'user_id': 42}
        ```
    """
    return _log_context.get().copy()


def clear_log_context() -> None:
    """Clear all logging context for current async task/thread.

    Usually not needed as context is automatically isolated per request,
    but can be useful in tests or long-running background tasks.

    Example:
        ```python
        # In test teardown
        clear_log_context()

        # In background task that processes multiple items
        for item in items:
            clear_log_context()
            set_log_context(item_id=item.id)
            process_item(item)
        ```
    """
    _log_context.set({})


def update_log_context(**kwargs: Any) -> None:
    """Update logging context with new values.

    Alias for set_log_context() for clarity when adding to existing context.

    Args:
        **kwargs: Key-value pairs to add/update in logging context.

    Example:
        ```python
        set_log_context(request_id="abc-123")
        update_log_context(user_id=42)  # Now has both request_id and user_id
        ```
    """
    set_log_context(**kwargs)


def remove_from_log_context(*keys: str) -> None:
    """Remove specific keys from logging context.

    Args:
        *keys: Keys to remove from context.

    Example:
        ```python
        set_log_context(request_id="abc-123", temp="value")
        remove_from_log_context("temp")  # Only request_id remains
        ```
    """
    current = _log_context.get().copy()
    for key in keys:
        current.pop(key, None)
    _log_context.set(current)


class ContextInjectingFilter(logging.Filter):
    """Logging filter that automatically injects context into LogRecord.

    This filter reads from the contextvars-based log context and adds
    all context fields to the LogRecord, making them available to
    formatters (especially JSONFormatter) without any code changes.

    The filter is applied to the root logger, so all loggers benefit
    from automatic context injection.

    Example:
        ```python
        # In logging config
        config = {
            "filters": {
                "context": {
                    "()": "example_service.infra.logging.context.ContextInjectingFilter"
                }
            },
            "root": {
                "level": "INFO",
                "handlers": ["queue"],
                "filters": ["context"]  # Auto-inject context
            }
        }
        ```
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Inject context into log record.

        Args:
            record: The log record to enhance with context.

        Returns:
            True (always allow the record to be logged).
        """
        # Get current context
        context = _log_context.get()

        # Inject all context fields into the record
        # This makes them available to formatters
        for key, value in context.items():
            # Don't overwrite existing attributes
            if not hasattr(record, key):
                setattr(record, key, value)

        return True


class ContextBoundLogger(logging.LoggerAdapter):
    """Logger adapter that binds context to a logger instance.

    Provides a more ergonomic API for structured logging with bound context,
    inspired by loguru's bind() method. Useful when you want a logger with
    permanent context that doesn't use the global ContextVar.

    Example:
        ```python
        # Create base logger
        logger = logging.getLogger(__name__)

        # Bind context to create specialized logger
        user_logger = ContextBoundLogger(logger, request_id="abc-123", user_id=42)
        user_logger.info("User action")  # Always includes request_id and user_id

        # Can chain bindings
        payment_logger = user_logger.bind(payment_id="pay-789")
        payment_logger.info("Processing payment")  # Includes all context
        ```
    """

    def __init__(self, logger: logging.Logger, **context: Any) -> None:
        """Initialize bound logger with context.

        Args:
            logger: Base logger to wrap.
            **context: Context fields to bind to this logger.
        """
        super().__init__(logger, context)

    def bind(self, **context: Any) -> ContextBoundLogger:
        """Create new logger with additional bound context.

        Args:
            **context: Additional context fields to bind.

        Returns:
            New ContextBoundLogger with combined context.

        Example:
            ```python
            base = ContextBoundLogger(logger, service="api")
            request = base.bind(request_id="123")
            request.info("Processing")  # Has both service and request_id
            ```
        """
        # Merge existing context with new context
        merged = {**self.extra, **context}
        return ContextBoundLogger(self.logger, **merged)

    def process(self, msg: str, kwargs: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Process log message and kwargs to include bound context.

        Args:
            msg: Log message.
            kwargs: Keyword arguments passed to logging call.

        Returns:
            Tuple of (message, modified kwargs with context in extra).
        """
        # Merge bound context with any extra fields passed to the log call
        extra = kwargs.get("extra", {})
        kwargs["extra"] = {**self.extra, **extra}
        return msg, kwargs


def get_logger(name: str, **context: Any) -> ContextBoundLogger:
    """Get logger with bound context.

    Args:
        name: Logger name.
        **context: Context to add to all log messages.

    Returns:
        Logger adapter with context.

    Example:
        ```python
        logger = get_logger(__name__, request_id="r-123", tenant="acme")
        logger.info("User logged in", extra={"user_id": "u-456"})
        ```
    """
    base_logger = logging.getLogger(name)
    return ContextBoundLogger(base_logger, **context)
