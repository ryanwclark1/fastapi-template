"""Logging configuration setup.

Provides production-ready logging configuration using:
- dictConfig for flexible configuration
- QueueHandler + QueueListener for non-blocking I/O
- ContextInjectingFilter for automatic context propagation
- All handlers on root logger (child loggers propagate)
- JSONL format for machine parsing (Loki-ready)
"""

from __future__ import annotations

import atexit
import logging
import logging.config
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
from pathlib import Path
from queue import Queue
from typing import TYPE_CHECKING, Any

# Global queue and listener for async logging
_log_queue: Queue[logging.LogRecord] | None = None
_listener: QueueListener | None = None
logger = logging.getLogger(__name__)
_LOGGING_INITIALIZED = False

if TYPE_CHECKING:
    from example_service.core.settings.logs import LoggingSettings


def complete() -> None:
    """Wait for all queued log records to be processed.

    Inspired by loguru's logger.complete() method. Ensures all logs
    in the queue are flushed and written before continuing. Useful
    for graceful shutdown to avoid losing logs.

    This function blocks until the QueueListener has processed all
    pending log records. Call this before application exit to ensure
    all logs are written.

    Example:
            from example_service.infra.logging import configure_logging, complete
        import logging

        # Configure logging
        configure_logging(log_level="INFO", file_path="app.log")

        logger = logging.getLogger(__name__)
        logger.info("Starting application")

        # ... application code ...

        logger.info("Shutting down")
        complete()  # Wait for all logs to be written

    Note:
        - This is automatically called on process exit via atexit handler
        - Only needed if you want to ensure logs are flushed mid-execution
        - Blocks until queue is empty (usually <1 second)
    """
    global _log_queue, _listener

    if _log_queue is None or _listener is None:
        return

    # Wait for queue to be empty
    # The queue.join() waits for all tasks to be marked done
    # However, Queue from queue module doesn't have join() method
    # So we just wait for the queue to be empty
    import time

    max_wait = 5.0  # Maximum 5 seconds
    start = time.time()

    while not _log_queue.empty() and (time.time() - start) < max_wait:
        time.sleep(0.01)  # 10ms polling interval

    # Give a bit more time for last records to be written
    time.sleep(0.05)


def shutdown() -> None:
    """Shutdown logging system and stop QueueListener.

    Stops the QueueListener and flushes all pending logs. This is
    automatically called via atexit handler, but can be called manually
    if needed.

    Example:
            from example_service.infra.logging import shutdown

        # Explicitly shutdown logging
        shutdown()
    """
    global _log_queue, _listener

    if _listener is not None:
        # Complete any pending logs first
        complete()

        # Stop the listener
        _listener.stop()
        _listener = None

    _log_queue = None


def setup_logging(
    log_settings: LoggingSettings | None = None,
    *,
    force: bool = False,
    **configure_kwargs: Any,
) -> None:
    """Ensure logging is configured once across entrypoints.

    Args:
        log_settings: Optional logging settings instance. If omitted, settings
            are loaded via get_logging_settings().
        force: Reconfigure logging even if it was already initialized.
        **configure_kwargs: Explicit overrides for configure_logging().
    """
    global _LOGGING_INITIALIZED

    if _LOGGING_INITIALIZED and not force:
        return

    settings_obj = log_settings
    if settings_obj is None:
        from example_service.core.settings import get_logging_settings

        settings_obj = get_logging_settings()

    log_config: dict[str, Any] = {}
    if hasattr(settings_obj, "to_logging_kwargs"):
        log_config = settings_obj.to_logging_kwargs()  # type: ignore[attr-defined]

    if configure_kwargs:
        log_config = {**log_config, **configure_kwargs}

    configure_logging(**log_config)
    _LOGGING_INITIALIZED = True


def configure_logging(
    log_level: str = "INFO",
    console_level: str | None = None,
    file_level: str | None = None,
    file_path: str | Path | None = None,
    json_logs: bool = True,
    console_enabled: bool = True,
    include_context: bool = True,
    capture_warnings: bool = True,
    include_function_name: bool = False,
    include_process_info: bool = False,
    include_thread_info: bool = False,
    file_max_bytes: int = 10 * 1024 * 1024,
    file_backup_count: int = 5,
    enable_sampling: bool = False,
    sampling_rate_health: float = 0.001,
    sampling_rate_metrics: float = 0.01,
    sampling_rate_default: float = 1.0,
    enable_rate_limit: bool = False,
    rate_limit_max_per_second: int = 100,
    colorize: bool | None = None,
    colorize_message: bool = False,
    level_colors: dict[str, str | tuple[int, int, int]] | None = None,
    **kwargs: Any,
) -> None:
    """Configure logging with dictConfig and QueueHandler pattern.

    Uses Python's logging.config.dictConfig exclusively for robust,
    production-ready logging configuration. All handlers are attached
    to the root logger; application loggers propagate up.

    Args:
        log_level: Root logger level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        console_level: Console handler level. If None, uses log_level.
        file_level: File handler level. If None, uses log_level.
        file_path: Path to log file. None disables file logging.
        json_logs: Enable JSONL (JSON Lines) structured logging.
        console_enabled: Enable console/stderr logging.
        include_context: Enable ContextInjectingFilter for auto context.
        capture_warnings: Forward Python warnings to logging system.
        include_function_name: Include function name in records (adds overhead).
        include_process_info: Include process ID and name in records.
        include_thread_info: Include thread ID and name in records.
        file_max_bytes: Maximum log file size before rotation.
        file_backup_count: Number of rotated log files to keep.
        enable_sampling: Enable log sampling for high-volume endpoints.
        sampling_rate_health: Sample rate for health check logs (0.001 = 0.1%).
        sampling_rate_metrics: Sample rate for metrics logs (0.01 = 1%).
        sampling_rate_default: Default sample rate (1.0 = 100%).
        enable_rate_limit: Enable rate limiting to prevent log storms.
        rate_limit_max_per_second: Max logs per second when rate limiting.
        colorize: Enable console colors. If None, auto-detect (respects NO_COLOR/FORCE_COLOR).
        colorize_message: If True, colorize entire message (not just level name).
        level_colors: Custom color mapping for log levels. Values can be ANSI strings,
            RGB tuples (e.g., (255, 0, 0)), or hex strings (e.g., "#FF0000").
        **kwargs: Additional settings (include_uvicorn, etc.).

    Example:
            # Recommended: Use LoggingSettings
        from example_service.core.settings import get_logging_settings
        log_settings = get_logging_settings()
        configure_logging(**log_settings.to_logging_kwargs())

        # Or: Direct parameters with per-handler levels
        configure_logging(
            log_level="DEBUG",
            console_level="ERROR",  # Only errors to console
            file_level="INFO",      # Info+ to file
            json_logs=True
        )
    """
    global _log_queue, _listener
    if kwargs:
        logger.debug("Unused logging kwargs supplied: %s", ", ".join(sorted(kwargs.keys())))

    # Enable Python warnings capture if requested
    if capture_warnings:
        logging.captureWarnings(True)

    # Use settings-driven dictConfig
    _configure_with_dictconfig(
        log_level=log_level,
        console_level=console_level or log_level,
        file_level=file_level or log_level,
        file_path=Path(file_path) if file_path else None,
        json_logs=json_logs,
        console_enabled=console_enabled,
        include_context=include_context,
        include_function_name=include_function_name,
        include_process_info=include_process_info,
        include_thread_info=include_thread_info,
        file_max_bytes=file_max_bytes,
        file_backup_count=file_backup_count,
        enable_sampling=enable_sampling,
        sampling_rate_health=sampling_rate_health,
        sampling_rate_metrics=sampling_rate_metrics,
        sampling_rate_default=sampling_rate_default,
        enable_rate_limit=enable_rate_limit,
        rate_limit_max_per_second=rate_limit_max_per_second,
        colorize=colorize,
        colorize_message=colorize_message,
        level_colors=level_colors,
    )


def _configure_with_dictconfig(
    log_level: str,
    console_level: str,
    file_level: str,
    file_path: Path | None,
    json_logs: bool,
    console_enabled: bool,
    include_context: bool,
    include_function_name: bool,
    include_process_info: bool,
    include_thread_info: bool,
    file_max_bytes: int,
    file_backup_count: int,
    enable_sampling: bool,
    sampling_rate_health: float,
    sampling_rate_metrics: float,
    sampling_rate_default: float,
    enable_rate_limit: bool,
    rate_limit_max_per_second: int,
    colorize: bool | None,
    colorize_message: bool,
    level_colors: dict[str, str | tuple[int, int, int]] | None,
) -> None:
    """Configure logging using dictConfig with QueueHandler pattern.

    This is the primary configuration function that builds a logging
    configuration dict and applies it via logging.config.dictConfig.

    All handlers are attached to a QueueListener for non-blocking I/O,
    and the root logger gets a single QueueHandler.

    Args:
        log_level: Root logger level.
        console_level: Console handler level.
        file_level: File handler level.
        file_path: Path to log file or None.
        json_logs: Use JSONL format.
        console_enabled: Enable console handler.
        include_context: Add ContextInjectingFilter.
        include_function_name: Include function name in logs.
        include_process_info: Include process info in logs.
        include_thread_info: Include thread info in logs.
        file_max_bytes: Max file size before rotation.
        file_backup_count: Number of backup files to keep.
        colorize: Enable console colors (None=auto-detect).
        colorize_message: Colorize entire message vs just level.
    """
    global _log_queue, _listener

    # Create log directory if file logging is enabled
    if file_path:
        file_path.parent.mkdir(parents=True, exist_ok=True)

    # Build formatters configuration
    formatters_config = _build_formatters_config(
        json_logs=json_logs,
        include_function_name=include_function_name,
        include_process_info=include_process_info,
        include_thread_info=include_thread_info,
    )

    # Build filters configuration
    filters_config = _build_filters_config(
        include_context=include_context,
        enable_sampling=enable_sampling,
        sampling_rate_health=sampling_rate_health,
        sampling_rate_metrics=sampling_rate_metrics,
        sampling_rate_default=sampling_rate_default,
        enable_rate_limit=enable_rate_limit,
        rate_limit_max_per_second=rate_limit_max_per_second,
    )

    # Build handlers configuration (for QueueListener, not root)
    handlers_config = _build_handlers_config(
        console_enabled=console_enabled,
        console_level=console_level,
        file_path=file_path,
        file_level=file_level,
        file_max_bytes=file_max_bytes,
        file_backup_count=file_backup_count,
        json_logs=json_logs,
    )

    # Build list of filters to apply to root logger
    root_filters = []
    if include_context:
        root_filters.append("context")
    if enable_sampling:
        root_filters.append("sampling")
    if enable_rate_limit:
        root_filters.append("rate_limit")

    # Build the dictConfig dict
    logging_config: dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": formatters_config,
        "filters": filters_config,
        # Note: handlers_config is NOT used in dictConfig
        # Handlers are created manually and attached to QueueListener
        "root": {
            "level": log_level.upper(),
            "handlers": [],  # Will add QueueHandler after setup
            "filters": root_filters,
        },
    }

    # Apply dictConfig (sets up root logger and filters)
    logging.config.dictConfig(logging_config)

    # Now set up QueueHandler + QueueListener pattern
    _setup_queue_logging(
        console_enabled=console_enabled,
        file_path=file_path,
        console_level=console_level,
        file_level=file_level,
        file_max_bytes=file_max_bytes,
        file_backup_count=file_backup_count,
        json_logs=json_logs,
        colorize=colorize,
        colorize_message=colorize_message,
        level_colors=level_colors,
    )


def _build_formatters_config(
    json_logs: bool,
    include_function_name: bool,
    include_process_info: bool,
    include_thread_info: bool,
) -> dict[str, Any]:
    """Build formatters configuration for dictConfig.

    Args:
        json_logs: Use JSONL format.
        include_function_name: Include function name.
        include_process_info: Include process info.
        include_thread_info: Include thread info.

    Returns:
        Formatters configuration dict.
    """
    formatters: dict[str, Any] = {}

    if json_logs:
        # JSONL formatter (JSON Lines - one JSON object per line)
        fmt_keys = {
            "level": "levelname",
            "logger": "name",
            "message": "message",
        }

        # Add optional fields
        if include_function_name:
            fmt_keys["function"] = "funcName"

        formatters["json"] = {
            "()": "example_service.infra.logging.formatters.JSONFormatter",
            "fmt_keys": fmt_keys,
            "static": {"service": "example-service"},
        }
    else:
        # Human-readable text format
        format_parts = ["%(asctime)s", "%(levelname)s", "%(name)s"]

        if include_function_name:
            format_parts.append("%(funcName)s")
        if include_process_info:
            format_parts.append("[%(processName)s:%(process)d]")
        if include_thread_info:
            format_parts.append("[%(threadName)s:%(thread)d]")

        format_parts.append("%(message)s")

        formatters["text"] = {
            "format": " - ".join(format_parts),
            "datefmt": "%Y-%m-%d %H:%M:%S",
        }

    return formatters


def _build_filters_config(
    include_context: bool,
    enable_sampling: bool,
    sampling_rate_health: float,
    sampling_rate_metrics: float,
    sampling_rate_default: float,
    enable_rate_limit: bool,
    rate_limit_max_per_second: int,
) -> dict[str, Any]:
    """Build filters configuration for dictConfig.

    Args:
        include_context: Enable ContextInjectingFilter.
        enable_sampling: Enable log sampling.
        sampling_rate_health: Sample rate for health logs.
        sampling_rate_metrics: Sample rate for metrics logs.
        sampling_rate_default: Default sample rate.
        enable_rate_limit: Enable rate limiting.
        rate_limit_max_per_second: Max logs per second.

    Returns:
        Filters configuration dict.
    """
    filters: dict[str, Any] = {}

    if include_context:
        filters["context"] = {
            "()": "example_service.infra.logging.context.ContextInjectingFilter",
        }

    if enable_sampling:
        # Build sample rates dict for common noisy loggers
        sample_rates = {
            "example_service.app.api.health": sampling_rate_health,
            "example_service.api.health": sampling_rate_health,
            "example_service.app.api.metrics": sampling_rate_metrics,
            "example_service.api.metrics": sampling_rate_metrics,
            "uvicorn.access": sampling_rate_metrics,
            # Add more as needed
        }

        filters["sampling"] = {
            "()": "example_service.infra.logging.sampling.SamplingFilter",
            "sample_rates": sample_rates,
            "default_sample_rate": sampling_rate_default,
        }

    if enable_rate_limit:
        filters["rate_limit"] = {
            "()": "example_service.infra.logging.sampling.RateLimitFilter",
            "max_logs_per_window": rate_limit_max_per_second,
            "window_seconds": 1.0,
        }

    return filters


def _build_handlers_config(
    console_enabled: bool,
    console_level: str,
    file_path: Path | None,
    file_level: str,
    file_max_bytes: int,
    file_backup_count: int,
    json_logs: bool,
) -> dict[str, Any]:
    """Build handlers configuration (metadata, not dictConfig).

    Note: This is NOT for dictConfig. We create handlers manually
    and attach them to QueueListener. This function returns metadata
    used by _setup_queue_logging().

    Args:
        console_enabled: Enable console handler.
        console_level: Console handler level.
        file_path: File path or None.
        file_level: File handler level.
        file_max_bytes: Max file size.
        file_backup_count: Backup count.
        json_logs: Use JSON format.

    Returns:
        Handlers metadata dict.
    """
    return {
        "console_enabled": console_enabled,
        "console_level": console_level,
        "file_path": file_path,
        "file_level": file_level,
        "file_max_bytes": file_max_bytes,
        "file_backup_count": file_backup_count,
        "json_logs": json_logs,
    }


def _setup_queue_logging(
    console_enabled: bool,
    file_path: Path | None,
    console_level: str,
    file_level: str,
    file_max_bytes: int,
    file_backup_count: int,
    json_logs: bool,
    colorize: bool | None,
    colorize_message: bool,
    level_colors: dict[str, str | tuple[int, int, int]] | None,
) -> None:
    """Set up QueueHandler + QueueListener for non-blocking logging.

    Creates actual handler instances, attaches them to a QueueListener,
    and configures the root logger with a QueueHandler.

    Args:
        console_enabled: Enable console handler.
        file_path: File path or None.
        console_level: Console handler level.
        file_level: File handler level.
        file_max_bytes: Max file size.
        file_backup_count: Backup count.
        json_logs: Use JSON format.
        colorize: Enable colors (None=auto-detect).
        colorize_message: Colorize entire message.
        level_colors: Custom color mapping for log levels, or None for defaults.
    """
    global _log_queue, _listener

    from example_service.infra.logging.color_formatter import ColoredConsoleFormatter
    from example_service.infra.logging.formatters import JSONFormatter

    # Create queue for async logging
    _log_queue = Queue()

    # Create handlers list
    handlers: list[logging.Handler] = []

    # Console handler
    if console_enabled:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(getattr(logging, console_level.upper()))

        if json_logs:
            # JSON logs don't get colors (for machine parsing)
            console_handler.setFormatter(
                JSONFormatter(
                    fmt_keys={"level": "levelname", "logger": "name", "message": "message"},
                    static={"service": "example-service"},
                )
            )
        else:
            # Use colored formatter for human-readable logs
            console_handler.setFormatter(
                ColoredConsoleFormatter(
                    fmt="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                    colorize=colorize,
                    colorize_message=colorize_message,
                    level_colors=level_colors,
                )
            )
        handlers.append(console_handler)

    # File handler
    if file_path:
        file_handler = RotatingFileHandler(
            file_path,
            maxBytes=file_max_bytes,
            backupCount=file_backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(getattr(logging, file_level.upper()))

        if json_logs:
            file_handler.setFormatter(
                JSONFormatter(
                    fmt_keys={"level": "levelname", "logger": "name", "message": "message"},
                    static={"service": "example-service"},
                )
            )
        else:
            file_handler.setFormatter(
                logging.Formatter(
                    fmt="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                )
            )
        handlers.append(file_handler)

    # Create QueueListener with the handlers
    if handlers:
        _listener = QueueListener(_log_queue, *handlers, respect_handler_level=True)
        _listener.start()
        atexit.register(shutdown)  # Use shutdown() instead of _listener.stop

    # Add QueueHandler to root logger
    root = logging.getLogger()
    queue_handler = QueueHandler(_log_queue)
    root.addHandler(queue_handler)
