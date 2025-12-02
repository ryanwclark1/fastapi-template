"""Enhanced exception formatter with variable diagnosis.

Provides loguru-inspired exception formatting with variable values displayed
in tracebacks for better debugging. IMPORTANT: Only enable in development,
never in production (security risk).
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from types import TracebackType

logger = logging.getLogger(__name__)


class DiagnoseFormatter(logging.Formatter):
    """Formatter that includes variable values in exception tracebacks.

    Inspired by loguru's diagnose mode. Shows local variables at each
    stack frame when exceptions occur, making debugging significantly easier.

    **SECURITY WARNING**: This formatter exposes variable values which may
    include sensitive data (passwords, tokens, PII). Only use in development
    environments. NEVER enable in production.

    Example:
            import logging
        from example_service.infra.logging import DiagnoseFormatter

        handler = logging.StreamHandler()
        handler.setFormatter(DiagnoseFormatter(
            fmt='%(asctime)s | %(levelname)s | %(message)s',
            diagnose=True  # Only in development!
        ))

        logger = logging.getLogger(__name__)
        logger.addHandler(handler)

        try:
            user_id = 123
            token = "secret_token"
            result = risky_operation(user_id, token)
        except Exception:
            # Traceback will show: user_id=123, token="secret_token"
            logger.exception("Operation failed")

    Features:
        - Shows variable names and values at each stack frame
        - Color-coded output (if terminal supports it)
        - Configurable maximum variable value length
        - Can filter out sensitive variable names
    """

    def __init__(
        self,
        fmt: str | None = None,
        datefmt: str | None = None,
        style: Literal["%", "{", "$"] = "%",
        diagnose: bool = False,
        max_variable_length: int = 100,
        exclude_vars: set[str] | None = None,
    ) -> None:
        """Initialize diagnose formatter.

        Args:
            fmt: Log format string.
            datefmt: Date format string.
            style: Format style ('%', '{', or '$').
            diagnose: Enable variable diagnosis in tracebacks.
            max_variable_length: Maximum length of variable repr strings.
            exclude_vars: Variable names to exclude from diagnosis (e.g., {'password', 'token'}).
        """
        super().__init__(fmt, datefmt, style)
        self.diagnose = diagnose
        self.max_variable_length = max_variable_length
        self.exclude_vars = exclude_vars or {
            "password",
            "passwd",
            "pwd",
            "token",
            "secret",
            "api_key",
            "apikey",
            "auth",
            "authorization",
            "private_key",
            "session",
        }

    def formatException(
        self,
        ei: tuple[type[BaseException], BaseException, TracebackType | None]
        | tuple[None, None, None],
    ) -> str:
        """Format exception with optional variable diagnosis.

        Args:
            ei: Exception info tuple (type, value, traceback).

        Returns:
            Formatted exception string.
        """
        if not self.diagnose:
            # Standard exception formatting
            return super().formatException(ei)

        # Enhanced exception formatting with variable values
        if ei == (None, None, None):
            return super().formatException(ei)
        exc_type, exc_value, exc_tb = ei

        if exc_tb is None:
            return super().formatException(ei)

        # Build enhanced traceback
        lines = ["Traceback (most recent call last):"]

        # Walk the traceback
        tb: TracebackType | None = exc_tb
        while tb is not None:
            frame = tb.tb_frame
            lineno = tb.tb_lineno
            filename = frame.f_code.co_filename
            funcname = frame.f_code.co_name

            # Add standard traceback line
            lines.append(f'  File "{filename}", line {lineno}, in {funcname}')

            # Add source code line if available
            try:
                import linecache

                line = linecache.getline(filename, lineno).strip()
                if line:
                    lines.append(f"    {line}")
            except Exception as e:
                # Log expected linecache errors at debug level (file may not exist or be inaccessible)
                logger.debug("Failed to get source line from linecache: %s", e, exc_info=True)

            # Add local variables if diagnose enabled
            if self.diagnose:
                local_vars = frame.f_locals
                if local_vars:
                    lines.append("    Local variables:")
                    for var_name, var_value in sorted(local_vars.items()):
                        # Skip excluded variables
                        if var_name.lower() in self.exclude_vars:
                            lines.append(f"      {var_name} = <excluded>")
                            continue

                        # Skip internal variables
                        if var_name.startswith("__") and var_name.endswith("__"):
                            continue

                        # Format variable value
                        try:
                            value_repr = repr(var_value)
                            if len(value_repr) > self.max_variable_length:
                                value_repr = value_repr[: self.max_variable_length] + "..."
                            lines.append(f"      {var_name} = {value_repr}")
                        except Exception:
                            lines.append(f"      {var_name} = <error getting repr>")

        tb = tb.tb_next if tb is not None else None

        # Add exception type and message
        if exc_type is not None and exc_value is not None:
            lines.append(f"{exc_type.__name__}: {exc_value}")

        return "\n".join(lines)

    def format(self, record: logging.LogRecord) -> str:
        """Format log record with enhanced exception info if present.

        Args:
            record: Log record to format.

        Returns:
            Formatted log string.
        """
        # Format base message
        message = super().format(record)

        # Add enhanced exception info if present
        if record.exc_info and self.diagnose:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
            if record.exc_text:
                if message[-1:] != "\n":
                    message = message + "\n"
                message = message + record.exc_text

        return message


def create_diagnose_handler(
    sink: Any = None,
    level: str = "DEBUG",
    diagnose: bool = False,
    fmt: str | None = None,
) -> logging.Handler:
    """Create a handler with diagnose formatter.

    Convenience function for creating handlers with DiagnoseFormatter.

    Args:
        sink: Handler destination (StreamHandler if None).
        level: Log level.
        diagnose: Enable variable diagnosis.
        fmt: Log format string.

    Returns:
        Configured handler with DiagnoseFormatter.

    Example:
            import logging
        from example_service.infra.logging import create_diagnose_handler

        # Create handler for development
        handler = create_diagnose_handler(
            diagnose=True,  # Only in development!
            level="DEBUG"
        )

        logger = logging.getLogger(__name__)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
    """
    if sink is None:
        handler: logging.Handler = logging.StreamHandler(sys.stderr)
    elif isinstance(sink, logging.Handler):
        handler = sink
    else:
        # Assume it's a file path
        handler = logging.FileHandler(sink)

    handler.setLevel(getattr(logging, level.upper()))

    if fmt is None:
        fmt = "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"

    formatter = DiagnoseFormatter(
        fmt=fmt,
        datefmt="%Y-%m-%d %H:%M:%S",
        diagnose=diagnose,
    )

    handler.setFormatter(formatter)
    return handler


# Utility function to check if diagnose should be enabled
def should_enable_diagnose() -> bool:
    """Check if diagnose mode should be enabled based on environment.

    Returns:
        True if in development environment, False otherwise.

    Checks:
        - DEBUG environment variable
        - ENVIRONMENT environment variable
        - Python debug mode (-d flag)
    """
    import os

    # Check DEBUG flag
    if os.getenv("DEBUG", "").lower() in ("1", "true", "yes"):
        return True

    # Check ENVIRONMENT
    env = os.getenv("ENVIRONMENT", "").lower()
    if env in ("dev", "development", "local"):
        return True

    # Check Python debug mode
    return bool(sys.flags.debug)
