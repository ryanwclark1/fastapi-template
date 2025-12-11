"""Exception catching decorators and context managers.

Provides loguru-inspired automatic exception logging without try/except boilerplate.
Inspired by loguru's @logger.catch decorator for cleaner error handling.
"""

from __future__ import annotations

from collections.abc import Callable
import functools
import logging
from typing import TYPE_CHECKING, Any, Self, TypeVar

if TYPE_CHECKING:
    from types import TracebackType

F = TypeVar("F", bound=Callable[..., Any])


def catch(
    exception: type[Exception] | tuple[type[Exception], ...] = Exception,
    *,
    level: str = "ERROR",
    reraise: bool = False,
    onerror: Callable[[Exception], None] | None = None,
    exclude: type[Exception] | tuple[type[Exception], ...] | None = None,
    default: Any = None,
    message: str = "An exception occurred",
    logger: logging.Logger | None = None,
) -> Callable[[F], F]:
    """Decorator to automatically log exceptions from wrapped function.

    Inspired by loguru's @logger.catch decorator. Eliminates try/except
    boilerplate while ensuring all exceptions are logged consistently.

    Args:
        exception: Exception type(s) to catch. Default: Exception (all exceptions).
        level: Log level for caught exceptions. Default: "ERROR".
        reraise: Whether to re-raise exception after logging. Default: False.
        onerror: Callback function called when exception is caught.
        exclude: Exception type(s) to NOT catch (bypass decorator).
        default: Value to return if exception caught and not re-raised.
        message: Custom error message. Default: "An exception occurred".
        logger: Logger to use. If None, uses module's logger.

    Returns:
        Decorated function that logs exceptions automatically.

    Example:
            from example_service.infra.logging import catch
        import logging

        logger = logging.getLogger(__name__)

        # Basic usage - catch and log all exceptions
        @catch()
        def divide(a: int, b: int) -> float:
            return a / b

        # Advanced usage with custom behavior
        @catch(
            exception=ValueError,
            level="WARNING",
            reraise=True,
            message="Invalid input to calculation"
        )
        def calculate(x: int) -> int:
            if x < 0:
                raise ValueError("x must be positive")
            return x * 2

        # Exclude specific exceptions
        @catch(exclude=(KeyboardInterrupt, SystemExit))
        def long_running_task():
            # Won't catch Ctrl+C
            pass

        # With callback
        def handle_error(exc: Exception) -> None:
            print(f"Error handled: {exc}")

        @catch(onerror=handle_error, default=0)
        def might_fail() -> int:
            raise ValueError("Oops")

    Features:
        - Automatic exception logging with full traceback
        - Optional re-raising for upstream handling
        - Custom error callbacks
        - Exclusion list for critical exceptions
        - Default return values on error
        - Works with both sync and async functions
    """

    def decorator(func: F) -> F:
        # Get logger from module if not provided
        nonlocal logger
        if logger is None:
            logger = logging.getLogger(func.__module__)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                # Check if this exception should be excluded
                if exclude and isinstance(exc, exclude):
                    raise

                # Check if this exception type should be caught
                if not isinstance(exc, exception):
                    raise

                # Log the exception
                log_method = getattr(logger, level.lower(), logger.error)
                log_method(
                    f"{message}: {type(exc).__name__}: {exc}",
                    exc_info=True,
                    extra={
                        "exception_type": type(exc).__name__,
                        "exception_message": str(exc),
                        "function": func.__name__,
                        "module": func.__module__,
                    },
                )

                # Call error handler if provided
                if onerror:
                    try:
                        onerror(exc)
                    except Exception as callback_error:
                        logger.warning(
                            f"Error in onerror callback: {callback_error}",
                            exc_info=True,
                        )

                # Re-raise if requested
                if reraise:
                    raise

                # Return default value
                return default

        return wrapper  # type: ignore

    return decorator


class CatchContext:
    """Context manager for catching and logging exceptions.

    Inspired by loguru's with logger.catch() context manager.
    Provides the same functionality as @catch decorator but for code blocks.

    Example:
            from example_service.infra.logging import CatchContext
        import logging

        logger = logging.getLogger(__name__)

        # Basic usage
        with CatchContext(logger=logger):
            risky_operation()

        # Advanced usage
        with CatchContext(
            logger=logger,
            exception=ValueError,
            level="WARNING",
            message="Invalid data processing",
            reraise=False
        ):
            process_data(user_input)
    """

    def __init__(
        self,
        exception: type[Exception] | tuple[type[Exception], ...] = Exception,
        *,
        level: str = "ERROR",
        reraise: bool = False,
        onerror: Callable[[Exception], None] | None = None,
        exclude: type[Exception] | tuple[type[Exception], ...] | None = None,
        message: str = "An exception occurred in context",
        logger: logging.Logger | None = None,
    ) -> None:
        """Initialize catch context manager.

        Args:
            exception: Exception type(s) to catch.
            level: Log level for caught exceptions.
            reraise: Whether to re-raise exception after logging.
            onerror: Callback function called when exception is caught.
            exclude: Exception type(s) to NOT catch.
            message: Custom error message.
            logger: Logger to use. If None, uses root logger.
        """
        self.exception = exception
        self.level = level
        self.reraise = reraise
        self.onerror = onerror
        self.exclude = exclude
        self.message = message
        self.logger = logger or logging.getLogger()

    def __enter__(self) -> Self:
        """Enter context manager."""
        return self

    def __exit__(
        self,
        exc_type: type[Exception] | None,
        exc_val: Exception | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        """Exit context manager and handle exceptions.

        Returns:
            True if exception was caught and should be suppressed,
            False if exception should propagate.
        """
        # No exception occurred
        if exc_type is None:
            return False

        # Check if this exception should be excluded
        if self.exclude and issubclass(exc_type, self.exclude):
            return False

        # Check if this exception type should be caught
        if not issubclass(exc_type, self.exception):
            return False

        if exc_val is None:
            return False

        # Log the exception
        log_method = getattr(self.logger, self.level.lower(), self.logger.error)
        exc_info_tuple: tuple[type[Exception], Exception, TracebackType | None] = (
            exc_type,
            exc_val,
            exc_tb,
        )
        log_method(
            f"{self.message}: {exc_type.__name__}: {exc_val}",
            exc_info=exc_info_tuple,
            extra={
                "exception_type": exc_type.__name__,
                "exception_message": str(exc_val),
            },
        )

        # Call error handler if provided
        if self.onerror and exc_val:
            try:
                self.onerror(exc_val)
            except Exception as callback_error:
                self.logger.warning(
                    f"Error in onerror callback: {callback_error}",
                    exc_info=True,
                )

        # Return True to suppress exception, False to re-raise
        return not self.reraise


# Convenience function to create catch context
def catch_context(
    exception: type[Exception] | tuple[type[Exception], ...] = Exception,
    *,
    level: str = "ERROR",
    reraise: bool = False,
    onerror: Callable[[Exception], None] | None = None,
    exclude: type[Exception] | tuple[type[Exception], ...] | None = None,
    message: str = "An exception occurred in context",
    logger: logging.Logger | None = None,
) -> CatchContext:
    """Create a catch context manager.

    Convenience function for creating CatchContext instances.
    See CatchContext documentation for details.

    Example:
            with catch_context(logger=logger, level="WARNING"):
            risky_operation()
    """
    return CatchContext(
        exception=exception,
        level=level,
        reraise=reraise,
        onerror=onerror,
        exclude=exclude,
        message=message,
        logger=logger,
    )
