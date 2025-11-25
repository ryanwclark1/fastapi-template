"""Operation logging decorators and context managers.

Provides reusable logging patterns for database operations, service methods,
and API endpoints. Designed to complement (not duplicate) OpenTelemetry traces.

Key features:
- Automatic entry/exit logging with duration
- Lazy evaluation for DEBUG logs (zero overhead when disabled)
- Structured extra fields for queryability
- Integration with existing context injection

Example:
    from example_service.infra.logging.operations import (
        log_db_operation,
        log_service_op,
        operation_context,
    )

    class UserRepository(BaseRepository[User]):
        @log_db_operation("get")
        async def get(self, session, id):
            return await session.get(User, id)

    class UserService(BaseService):
        @log_service_op("create_user")
        async def create_user(self, payload: UserCreate) -> User:
            return await self.repo.create(self.session, User(**payload.dict()))

    async with operation_context("process_batch", count=100) as ctx:
        results = await process_items(items)
        ctx.set_result(processed=len(results))
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
from contextlib import asynccontextmanager, contextmanager
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator

P = ParamSpec("P")
R = TypeVar("R")


def log_operation(
    operation_type: str,
    *,
    level: int = logging.DEBUG,
    log_args: bool = False,
    include_timing: bool = True,
    error_level: int = logging.ERROR,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Generic operation logging decorator.

    Logs operation entry, exit (with duration), and errors. Uses lazy evaluation
    to avoid overhead when the log level is disabled.

    Args:
        operation_type: Operation category (e.g., "db.get", "service.create")
        level: Log level for success messages (default: DEBUG)
        log_args: Whether to include function arguments in logs
        include_timing: Whether to include execution duration
        error_level: Log level for errors (default: ERROR)

    Returns:
        Decorated function with automatic logging

    Example:
        @log_operation("db.query", level=logging.DEBUG)
        async def find_users(self, session, filters):
            ...
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        logger = logging.getLogger(func.__module__)
        func_name = func.__name__
        is_async = asyncio.iscoroutinefunction(func)

        @functools.wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            # Skip logging if level not enabled (performance optimization)
            should_log = logger.isEnabledFor(level)
            should_log_errors = logger.isEnabledFor(error_level)

            if not should_log and not should_log_errors:
                return await func(*args, **kwargs)

            extra: dict[str, Any] = {
                "operation": operation_type,
                "function": func_name,
            }

            if log_args and args:
                # Skip self/cls and session args for cleaner logs
                extra["args"] = _sanitize_args(args[2:] if len(args) > 2 else ())

            start_time = time.perf_counter() if include_timing else 0

            try:
                result = await func(*args, **kwargs)

                if should_log:
                    if include_timing:
                        extra["duration_ms"] = round((time.perf_counter() - start_time) * 1000, 2)
                    extra["success"] = True
                    logger.log(level, f"{operation_type}.{func_name}", extra=extra)

                return result

            except Exception as exc:
                if should_log_errors:
                    if include_timing:
                        extra["duration_ms"] = round((time.perf_counter() - start_time) * 1000, 2)
                    extra["success"] = False
                    extra["error_type"] = type(exc).__name__
                    extra["error"] = str(exc)
                    logger.log(error_level, f"{operation_type}.{func_name} failed", extra=extra)
                raise

        @functools.wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            should_log = logger.isEnabledFor(level)
            should_log_errors = logger.isEnabledFor(error_level)

            if not should_log and not should_log_errors:
                return func(*args, **kwargs)

            extra: dict[str, Any] = {
                "operation": operation_type,
                "function": func_name,
            }

            start_time = time.perf_counter() if include_timing else 0

            try:
                result = func(*args, **kwargs)

                if should_log:
                    if include_timing:
                        extra["duration_ms"] = round((time.perf_counter() - start_time) * 1000, 2)
                    extra["success"] = True
                    logger.log(level, f"{operation_type}.{func_name}", extra=extra)

                return result

            except Exception as exc:
                if should_log_errors:
                    if include_timing:
                        extra["duration_ms"] = round((time.perf_counter() - start_time) * 1000, 2)
                    extra["success"] = False
                    extra["error_type"] = type(exc).__name__
                    extra["error"] = str(exc)
                    logger.log(error_level, f"{operation_type}.{func_name} failed", extra=extra)
                raise

        return async_wrapper if is_async else sync_wrapper  # type: ignore[return-value]

    return decorator


def log_db_operation(
    operation: str,
    *,
    level: int = logging.DEBUG,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator for database repository operations.

    Specialized for repository methods with automatic entity detection.
    Logs at DEBUG level by default since OTEL captures query timing.

    Args:
        operation: Short operation name (e.g., "get", "create", "list")
        level: Log level (default: DEBUG)

    Example:
        @log_db_operation("get")
        async def get(self, session, id):
            return await session.get(self.model, id)

        @log_db_operation("search")
        async def search(self, session, query):
            ...
    """
    return log_operation(f"db.{operation}", level=level)


def log_service_op(
    operation: str,
    *,
    level: int = logging.INFO,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator for service layer operations.

    Logs at INFO level by default since service operations represent
    business events worth tracking.

    Args:
        operation: Operation name (e.g., "create_user", "send_notification")
        level: Log level (default: INFO)

    Example:
        @log_service_op("create_reminder")
        async def create_reminder(self, payload: ReminderCreate) -> Reminder:
            ...
    """
    return log_operation(f"service.{operation}", level=level)


def log_endpoint(
    operation: str,
    *,
    level: int = logging.DEBUG,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator for API endpoint handlers.

    Use sparingly - request logging middleware handles most cases.
    Only add where you need business-specific context not captured by middleware.

    Args:
        operation: Endpoint operation name
        level: Log level (default: DEBUG)

    Example:
        @router.get("/search")
        @log_endpoint("search_reminders")
        async def search_reminders(query: str = None):
            ...
    """
    return log_operation(f"endpoint.{operation}", level=level)


class OperationContext:
    """Helper class for operation context managers.

    Allows setting additional result data during the operation.
    """

    __slots__ = ("_extra",)

    def __init__(self) -> None:
        self._extra: dict[str, Any] = {}

    def set_result(self, **kwargs: Any) -> None:
        """Add result data to be logged on completion."""
        self._extra.update(kwargs)

    def set(self, key: str, value: Any) -> None:
        """Add a single result value."""
        self._extra[key] = value


@asynccontextmanager
async def operation_context(
    operation_name: str,
    *,
    logger: logging.Logger | None = None,
    level: int = logging.DEBUG,
    error_level: int = logging.ERROR,
    **context_data: Any,
) -> AsyncIterator[OperationContext]:
    """Async context manager for logging operation blocks.

    Useful for operations that span multiple calls or aren't easily
    wrapped with a decorator.

    Args:
        operation_name: Name for the operation
        logger: Logger to use (default: module logger)
        level: Log level for success (default: DEBUG)
        error_level: Log level for errors (default: ERROR)
        **context_data: Additional context to include in logs

    Yields:
        OperationContext for adding result data

    Example:
        async with operation_context("process_batch", batch_size=100) as ctx:
            results = await process_items(items)
            ctx.set_result(processed=len(results), failed=0)
    """
    log = logger or logging.getLogger(__name__)
    ctx = OperationContext()

    should_log = log.isEnabledFor(level)
    should_log_errors = log.isEnabledFor(error_level)

    if not should_log and not should_log_errors:
        yield ctx
        return

    start_time = time.perf_counter()
    extra: dict[str, Any] = {"operation": operation_name, **context_data}

    try:
        yield ctx

        if should_log:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            log.log(
                level,
                f"{operation_name} completed",
                extra={**extra, **ctx._extra, "duration_ms": duration_ms, "success": True},
            )

    except Exception as exc:
        if should_log_errors:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            log.log(
                error_level,
                f"{operation_name} failed: {exc}",
                extra={
                    **extra,
                    **ctx._extra,
                    "duration_ms": duration_ms,
                    "success": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
        raise


@contextmanager
def operation_context_sync(
    operation_name: str,
    *,
    logger: logging.Logger | None = None,
    level: int = logging.DEBUG,
    error_level: int = logging.ERROR,
    **context_data: Any,
) -> Iterator[OperationContext]:
    """Sync context manager for logging operation blocks.

    Same as operation_context but for synchronous code.

    Example:
        with operation_context_sync("validate_config", config_path=path) as ctx:
            config = load_config(path)
            ctx.set_result(keys_loaded=len(config))
    """
    log = logger or logging.getLogger(__name__)
    ctx = OperationContext()

    should_log = log.isEnabledFor(level)
    should_log_errors = log.isEnabledFor(error_level)

    if not should_log and not should_log_errors:
        yield ctx
        return

    start_time = time.perf_counter()
    extra: dict[str, Any] = {"operation": operation_name, **context_data}

    try:
        yield ctx

        if should_log:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            log.log(
                level,
                f"{operation_name} completed",
                extra={**extra, **ctx._extra, "duration_ms": duration_ms, "success": True},
            )

    except Exception as exc:
        if should_log_errors:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            log.log(
                error_level,
                f"{operation_name} failed: {exc}",
                extra={
                    **extra,
                    **ctx._extra,
                    "duration_ms": duration_ms,
                    "success": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
        raise


def _sanitize_args(args: tuple[Any, ...]) -> list[str]:
    """Convert args to safe string representations for logging.

    Skips complex objects and limits string lengths.
    """
    result = []
    for arg in args:
        if isinstance(arg, (str, int, float, bool, type(None))):
            s = str(arg)
            result.append(s[:100] if len(s) > 100 else s)
        else:
            result.append(f"<{type(arg).__name__}>")
    return result
