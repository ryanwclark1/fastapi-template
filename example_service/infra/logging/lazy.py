"""Lazy evaluation support for logging.

Provides loguru-inspired lazy evaluation of expensive log operations,
ensuring that expensive computations are only performed if the log
level is actually enabled.

This is particularly useful for debug logging where you want rich context
but don't want to pay the performance cost in production where debug logs
are disabled.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any


class LazyString:
    """Lazy-evaluated string that defers computation until needed.

    Wraps a callable that produces a string, only invoking it when
    the string representation is actually required (e.g., when the
    log message is formatted).

    Example:
        ```python
        def expensive_computation():
            # Heavy processing...
            return f"Result: {complex_data}"

        logger.debug("Status: %s", LazyString(expensive_computation))
        # If DEBUG is disabled, expensive_computation() never runs!
        ```
    """

    __slots__ = ("_func",)

    def __init__(self, func: Callable[[], Any]) -> None:
        """Initialize lazy string.

        Args:
            func: Callable that returns the string value when invoked.
        """
        self._func = func

    def __str__(self) -> str:
        """Evaluate and return string representation.

        Returns:
            String result of calling the wrapped function.
        """
        result = self._func()
        return str(result)

    def __repr__(self) -> str:
        """Return representation of lazy string.

        Returns:
            Representation showing it's a lazy string.
        """
        return f"LazyString({self._func!r})"


class LazyLoggerAdapter(logging.LoggerAdapter):
    """Logger adapter that supports lazy evaluation of log messages.

    Extends standard LoggerAdapter to automatically detect and handle
    lambda functions in log arguments, providing loguru-style lazy
    evaluation without requiring the full loguru library.

    Example:
        ```python
        # Create lazy logger
        base_logger = logging.getLogger(__name__)
        logger = LazyLoggerAdapter(base_logger)

        # Use with lambdas for lazy evaluation
        logger.debug(lambda: f"Processing {expensive_call()}")
        # expensive_call() only runs if DEBUG is enabled!

        # Works with format args too
        logger.info("Status: %s", lambda: compute_status())
        ```
    """

    def log(
        self,
        level: int,
        msg: Any,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Log message with lazy evaluation support.

        Args:
            level: Numeric log level (e.g., logging.DEBUG).
            msg: Log message or callable returning message.
            *args: Format arguments (may include callables).
            **kwargs: Additional kwargs for logging.
        """
        # Check if logging is enabled for this level before doing any work
        if not self.isEnabledFor(level):
            return

        # Evaluate message if it's callable
        if callable(msg):
            msg = msg()

        # Evaluate any lazy args
        if args:
            evaluated_args = tuple(
                arg() if callable(arg) else arg for arg in args
            )
        else:
            evaluated_args = args

        # Call parent with evaluated values
        super().log(level, msg, *evaluated_args, **kwargs)

    def debug(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        """Log debug message with lazy evaluation.

        Args:
            msg: Message or callable returning message.
            *args: Format arguments (may include callables).
            **kwargs: Additional kwargs for logging.

        Example:
            ```python
            logger.debug(lambda: f"State: {expensive_state_dump()}")
            ```
        """
        self.log(logging.DEBUG, msg, *args, **kwargs)

    def info(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        """Log info message with lazy evaluation.

        Args:
            msg: Message or callable returning message.
            *args: Format arguments (may include callables).
            **kwargs: Additional kwargs for logging.
        """
        self.log(logging.INFO, msg, *args, **kwargs)

    def warning(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        """Log warning message with lazy evaluation.

        Args:
            msg: Message or callable returning message.
            *args: Format arguments (may include callables).
            **kwargs: Additional kwargs for logging.
        """
        self.log(logging.WARNING, msg, *args, **kwargs)

    def error(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        """Log error message with lazy evaluation.

        Args:
            msg: Message or callable returning message.
            *args: Format arguments (may include callables).
            **kwargs: Additional kwargs for logging.
        """
        self.log(logging.ERROR, msg, *args, **kwargs)

    def critical(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        """Log critical message with lazy evaluation.

        Args:
            msg: Message or callable returning message.
            *args: Format arguments (may include callables).
            **kwargs: Additional kwargs for logging.
        """
        self.log(logging.CRITICAL, msg, *args, **kwargs)

    def exception(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        """Log exception message with lazy evaluation.

        Args:
            msg: Message or callable returning message.
            *args: Format arguments (may include callables).
            **kwargs: Additional kwargs for logging.
        """
        kwargs.setdefault("exc_info", True)
        self.log(logging.ERROR, msg, *args, **kwargs)


def get_lazy_logger(name: str, **context: Any) -> LazyLoggerAdapter:
    """Get logger with lazy evaluation support.

    Creates a LazyLoggerAdapter that supports both lazy evaluation
    via callables and optional bound context.

    Args:
        name: Logger name (usually __name__).
        **context: Optional context to bind to logger.

    Returns:
        Logger adapter with lazy evaluation support.

    Example:
        ```python
        logger = get_lazy_logger(__name__, service="api")

        # Lazy evaluation with lambda
        logger.debug(lambda: f"Request data: {expensive_serialize(data)}")

        # Regular logging still works
        logger.info("Request completed")

        # With format args
        logger.debug("Value: %s", lambda: compute_value())
        ```
    """
    base_logger = logging.getLogger(name)
    return LazyLoggerAdapter(base_logger, context or {})


# Convenience function for creating lazy strings
def lazy(func: Callable[[], Any]) -> LazyString:
    """Create a lazy-evaluated string.

    Convenience function to wrap a callable in a LazyString.

    Args:
        func: Callable that returns the value when invoked.

    Returns:
        LazyString wrapper around the callable.

    Example:
        ```python
        logger.debug("Data: %s", lazy(lambda: expensive_dump(data)))
        # More concise than: LazyString(lambda: expensive_dump(data))
        ```
    """
    return LazyString(func)
