"""Optional logger customization (opt() method).

Provides loguru-inspired per-call logger customization without creating new loggers.
Allows fine-grained control over lazy evaluation, exception info, stack depth, etc.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
import logging
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType


class OptLoggerAdapter(logging.LoggerAdapter):
    """Logger adapter that provides opt() method for per-call customization.

    Inspired by loguru's logger.opt() method. Allows you to customize
    logger behavior on a per-call basis without creating new loggers.

    Features:
        - Lazy evaluation per-call
        - Include exception info automatically
        - Adjust stack depth for better source location
        - Custom record modification

    Example:
            from example_service.infra.logging import get_opt_logger
        import logging

        logger = get_opt_logger(__name__)

        # Lazy evaluation (only runs if DEBUG enabled)
        logger.opt(lazy=True).debug("Result: {}", expensive_computation)

        # Include exception info without raising
        try:
            risky_operation()
        except Exception:
            logger.opt(exception=True).error("Operation failed")

        # Adjust depth for wrapper functions
        def my_log_wrapper(msg):
            # depth=1 shows caller of my_log_wrapper, not my_log_wrapper itself
            logger.opt(depth=1).info(msg)

        # Chain multiple options
        logger.opt(lazy=True, exception=True).debug("Debug: {}", lambda: compute())
    """

    def __init__(
        self,
        logger: logging.Logger,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Initialize opt logger adapter.

        Args:
            logger: Underlying logger instance.
            extra: Extra context to include in all records.
        """
        super().__init__(logger, extra or {})
        self._lazy = False
        self._include_exception = False
        self._depth = 0
        self._record_patcher: Callable[[logging.LogRecord], None] | None = None

    def opt(
        self,
        *,
        lazy: bool = False,
        exception: bool = False,
        depth: int = 0,
        record: Callable[[logging.LogRecord], None] | None = None,
    ) -> OptLoggerAdapter:
        """Create a new adapter with modified options.

        Args:
            lazy: Enable lazy evaluation of message and args.
            exception: Include current exception info in log record.
            depth: Stack depth adjustment for finding calling function.
                   Useful for wrapper functions. depth=1 goes up one level.
            record: Callback to modify LogRecord before emission.

        Returns:
            New OptLoggerAdapter with specified options.

        Example:
                    # Lazy evaluation - only runs expensive_func() if INFO enabled
            logger.opt(lazy=True).info("Data: {}", expensive_func)

            # Include exception automatically
            try:
                1 / 0
            except Exception:
                logger.opt(exception=True).error("Math error")

            # Adjust depth for wrappers
            def log_wrapper(msg):
                logger.opt(depth=1).info(msg)  # Shows caller, not wrapper

            # Custom record modification
            def add_user_id(record):
                record.user_id = get_current_user_id()

            logger.opt(record=add_user_id).info("User action")
        """
        # Create new adapter with same logger but modified options
        extra_copy: dict[str, Any] = {}
        if self.extra is not None:
            extra_copy = dict(self.extra)
        new_adapter = OptLoggerAdapter(self.logger, extra_copy)
        new_adapter._lazy = lazy
        new_adapter._include_exception = exception
        new_adapter._depth = depth
        new_adapter._record_patcher = record
        return new_adapter

    def process(
        self, msg: object, kwargs: MutableMapping[str, object],
    ) -> tuple[object, MutableMapping[str, object]]:
        """Process log message and kwargs with configured options.

        Args:
            msg: Log message or callable (if lazy=True).
            kwargs: Keyword arguments to log method.

        Returns:
            Tuple of (processed_message, processed_kwargs).
        """
        # Handle lazy evaluation
        if self._lazy and callable(msg):
            try:
                msg = msg()
            except Exception as e:
                msg = f"<Error evaluating lazy message: {e}>"

        # Handle lazy args
        if self._lazy and "args" in kwargs:
            raw_args = kwargs.get("args")
            if isinstance(raw_args, tuple):
                evaluated_args = []
                for arg in raw_args:
                    if callable(arg):
                        try:
                            evaluated_args.append(arg())
                        except Exception as e:
                            evaluated_args.append(f"<Error: {e}>")
                    else:
                        evaluated_args.append(arg)
                kwargs["args"] = tuple(evaluated_args)

        # Include exception info if requested
        if self._include_exception:
            kwargs.setdefault("exc_info", True)

        # Add stack depth adjustment
        if self._depth > 0:
            kwargs.setdefault("stacklevel", 1 + self._depth)

        # Merge extra context
        extra_dict: dict[str, Any] = {}
        if self.extra is not None:
            extra_dict = dict(self.extra)
        if "extra" in kwargs:
            extra_val = kwargs["extra"]
            if isinstance(extra_val, Mapping):
                kwargs["extra"] = {**extra_dict, **extra_val}
            else:
                kwargs["extra"] = extra_dict
        else:
            kwargs["extra"] = extra_dict

        return msg, kwargs

    def _log(
        self,
        level: int,
        msg: object,
        args: tuple[object, ...] | Mapping[str, object],
        *,
        exc_info: bool
        | BaseException
        | tuple[type[BaseException], BaseException, TracebackType | None]
        | tuple[None, None, None]
        | None = None,
        extra: Mapping[str, object] | None = None,
        stack_info: bool = False,
        **kwargs: Any,
    ) -> None:
        """Low-level logging method with record patching support.

        Overrides logging.Logger._log to support record patching.
        """
        # Process message and kwargs
        extra_kwargs: dict[str, object] = cast("dict[str, object]", kwargs)
        stacklevel_value = extra_kwargs.pop("stacklevel", 1)
        log_kwargs_input: dict[str, object] = {
            "exc_info": exc_info,
            "extra": extra,
            "stack_info": stack_info,
            "stacklevel": stacklevel_value,
            **extra_kwargs,
        }
        msg, log_kwargs = self.process(msg, log_kwargs_input)

        # Extract processed values
        exc_info_obj = log_kwargs.pop("exc_info", None)
        exc_info = cast(
            "bool | BaseException | tuple[type[BaseException], BaseException, TracebackType | None] | tuple[None, None, None] | None",
            exc_info_obj,
        )
        extra_mapping = cast("Mapping[str, object] | None", log_kwargs.pop("extra", None))
        stack_info = bool(log_kwargs.pop("stack_info", False))
        stacklevel = cast("int", log_kwargs.pop("stacklevel", 1))

        # Call parent _log
        if hasattr(self.logger, "_log"):
            # Create kwargs dict for _log
            _log_kwargs = {
                "exc_info": exc_info,
                "extra": extra_mapping,
                "stack_info": stack_info,
                "stacklevel": stacklevel + 1,  # +1 for this wrapper
            }

            # Apply record patcher if provided
            if self._record_patcher:
                # Monkey-patch makeRecord temporarily
                original_make_record = self.logger.makeRecord

                def patched_make_record(*args: Any, **kwargs: Any) -> logging.LogRecord:
                    record = cast("logging.LogRecord", original_make_record(*args, **kwargs))
                    if self._record_patcher:
                        self._record_patcher(record)
                    return record

                self.logger.makeRecord = patched_make_record
                try:
                    self.logger._log(level, msg, args, **_log_kwargs)
                finally:
                    self.logger.makeRecord = original_make_record
            else:
                self.logger._log(level, msg, args, **_log_kwargs)

    # Override all log level methods to use _log
    def debug(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        """Log at DEBUG level with opt() customizations."""
        if self.isEnabledFor(logging.DEBUG):
            self._log(logging.DEBUG, msg, args, **kwargs)

    def info(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        """Log at INFO level with opt() customizations."""
        if self.isEnabledFor(logging.INFO):
            self._log(logging.INFO, msg, args, **kwargs)

    def warning(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        """Log at WARNING level with opt() customizations."""
        if self.isEnabledFor(logging.WARNING):
            self._log(logging.WARNING, msg, args, **kwargs)

    def error(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        """Log at ERROR level with opt() customizations."""
        if self.isEnabledFor(logging.ERROR):
            self._log(logging.ERROR, msg, args, **kwargs)

    def critical(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        """Log at CRITICAL level with opt() customizations."""
        if self.isEnabledFor(logging.CRITICAL):
            self._log(logging.CRITICAL, msg, args, **kwargs)

    def exception(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        """Log exception at ERROR level with opt() customizations."""
        kwargs.setdefault("exc_info", True)
        self.error(msg, *args, **kwargs)


def get_opt_logger(name: str | None = None) -> OptLoggerAdapter:
    """Get an OptLoggerAdapter for the specified logger name.

    Args:
        name: Logger name. If None, uses root logger.

    Returns:
        OptLoggerAdapter instance.

    Example:
            from example_service.infra.logging import get_opt_logger

        logger = get_opt_logger(__name__)

        # Use opt() for customization
        logger.opt(lazy=True).debug("Debug: {}", expensive_operation)
        logger.opt(exception=True).error("Error occurred")
    """
    base_logger = logging.getLogger(name)
    return OptLoggerAdapter(base_logger)
