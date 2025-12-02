"""Logging infrastructure.

Provides production-ready structured logging with:
- JSONL format for Loki/Elasticsearch ingestion
- Automatic context injection (request_id, user_id, etc.)
- QueueHandler + QueueListener for non-blocking I/O
- Per-handler log levels (console vs file)
- Lazy evaluation for expensive operations
- OpenTelemetry trace correlation
- Loguru-inspired features (catch decorator, opt method, diagnose mode)

Basic usage:
    # Automatic context injection (recommended)
    from example_service.infra.logging import set_log_context
    import logging

    logger = logging.getLogger(__name__)

    # Set context once, all logs include it
    set_log_context(request_id="abc-123", user_id=42)
    logger.info("Processing request")  # Automatically includes request_id and user_id

    # Lazy evaluation for expensive operations
    from example_service.infra.logging import get_lazy_logger

    lazy_logger = get_lazy_logger(__name__)
    lazy_logger.debug(lambda: f"Expensive: {compute_heavy_data()}")  # Only runs if DEBUG enabled

    # Catch decorator for automatic exception logging
    from example_service.infra.logging import catch

    @catch(level="ERROR", message="Division failed")
    def divide(a: int, b: int) -> float:
        return a / b  # Exceptions automatically logged

    # Opt method for per-call customization
    from example_service.infra.logging import get_opt_logger

    opt_logger = get_opt_logger(__name__)
    opt_logger.opt(lazy=True).debug("Result: {}", expensive_func)
    opt_logger.opt(exception=True).error("Failed")
"""

from example_service.infra.logging.color_convert import (
    hex_to_ansi,
    hex_to_ansi_bg,
    hex_to_rgb,
    rgb_to_ansi,
    rgb_to_ansi_16,
    rgb_to_ansi_256,
    rgb_to_ansi_bg,
    rgb_to_ansi_bg_16,
    rgb_to_ansi_bg_256,
    rgb_to_ansi_bg_truecolor,
    rgb_to_ansi_truecolor,
)
from example_service.infra.logging.color_formatter import (
    ColoredConsoleFormatter,
    MinimalColoredFormatter,
    create_colored_handler,
)
from example_service.infra.logging.color_modes import (
    ColorMode,
    color_mode_manager,
    detect_color_mode,
    get_color_mode,
    supports_color,
)
from example_service.infra.logging.colors import (
    ANSIColors,
    clear_color_cache,
    is_color_enabled,
    should_colorize,
    strip_ansi,
)
from example_service.infra.logging.config import (
    complete,
    configure_logging,
    setup_logging,
    shutdown,
)
from example_service.infra.logging.context import (
    ContextBoundLogger,
    ContextInjectingFilter,
    clear_log_context,
    get_log_context,
    get_logger,
    set_log_context,
    update_log_context,
)
from example_service.infra.logging.decorators import CatchContext, catch, catch_context
from example_service.infra.logging.diagnose import (
    DiagnoseFormatter,
    create_diagnose_handler,
    should_enable_diagnose,
)
from example_service.infra.logging.formatters import JSONFormatter
from example_service.infra.logging.lazy import (
    LazyLoggerAdapter,
    LazyString,
    get_lazy_logger,
    lazy,
)
from example_service.infra.logging.operations import (
    OperationContext,
    log_db_operation,
    log_endpoint,
    log_operation,
    log_service_op,
    operation_context,
    operation_context_sync,
)
from example_service.infra.logging.opt import OptLoggerAdapter, get_opt_logger
from example_service.infra.logging.sampling import (
    RateLimitFilter,
    SamplingFilter,
    create_sampling_config,
)

__all__ = [
    # Colors (loguru-inspired)
    "ANSIColors",
    "CatchContext",
    # Terminal capability detection
    "ColorMode",
    "ColoredConsoleFormatter",
    # Context-bound loggers
    "ContextBoundLogger",
    "ContextInjectingFilter",
    # Diagnose mode (loguru-inspired)
    "DiagnoseFormatter",
    # Formatters and filters
    "JSONFormatter",
    # Lazy evaluation
    "LazyLoggerAdapter",
    "LazyString",
    "MinimalColoredFormatter",
    "OperationContext",
    # Opt method (loguru-inspired)
    "OptLoggerAdapter",
    "RateLimitFilter",
    # Sampling and rate limiting
    "SamplingFilter",
    # Exception catching (loguru-inspired)
    "catch",
    "catch_context",
    "clear_color_cache",
    "clear_log_context",
    "color_mode_manager",
    "complete",
    # Configuration
    "configure_logging",
    "create_colored_handler",
    "create_diagnose_handler",
    "create_sampling_config",
    "detect_color_mode",
    "get_color_mode",
    "get_lazy_logger",
    "get_log_context",
    "get_logger",
    "get_opt_logger",
    "hex_to_ansi",
    "hex_to_ansi_bg",
    # RGB/Hex color conversion
    "hex_to_rgb",
    "is_color_enabled",
    "lazy",
    "log_db_operation",
    "log_endpoint",
    # Operation logging decorators and helpers
    "log_operation",
    "log_service_op",
    "operation_context",
    "operation_context_sync",
    "rgb_to_ansi",
    "rgb_to_ansi_16",
    "rgb_to_ansi_256",
    "rgb_to_ansi_bg",
    "rgb_to_ansi_bg_16",
    "rgb_to_ansi_bg_256",
    "rgb_to_ansi_bg_truecolor",
    "rgb_to_ansi_truecolor",
    # Context management (recommended)
    "set_log_context",
    "setup_logging",
    "should_colorize",
    "should_enable_diagnose",
    "shutdown",
    "strip_ansi",
    "supports_color",
    "update_log_context",
]
