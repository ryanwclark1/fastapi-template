"""Colored console formatter for enhanced readability.

Provides automatic colorization of console logs based on log level,
with intelligent detection of terminal capabilities.
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, Any, Literal

from example_service.infra.logging.color_convert import hex_to_ansi, rgb_to_ansi
from example_service.infra.logging.colors import (
    LEVEL_COLORS,
    ANSIColors,
    ColorSupport,
)

if TYPE_CHECKING:
    from types import TracebackType


class ColoredConsoleFormatter(logging.Formatter):
    """Formatter that adds colors to console output based on log level.

    Automatically detects terminal capabilities and respects NO_COLOR/FORCE_COLOR
    environment variables. Colors are only applied when appropriate.

    Features:
        - Level-based colorization (DEBUG=cyan, ERROR=red, etc.)
        - Automatic color detection per stream
        - Respects NO_COLOR and FORCE_COLOR standards
        - Customizable color scheme
        - Optional full message colorization

    Example:
            import logging
        import sys
        from example_service.infra.logging import ColoredConsoleFormatter

        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(ColoredConsoleFormatter(
            fmt='%(asctime)s | %(levelname)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))

        logger = logging.getLogger(__name__)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

        # These will be colorized automatically:
        logger.debug("Debug message")     # Cyan
        logger.info("Info message")       # Green
        logger.warning("Warning message") # Yellow
        logger.error("Error message")     # Red
    """

    def __init__(
        self,
        fmt: str | None = None,
        datefmt: str | None = None,
        style: Literal["%", "{", "$"] = "%",
        colorize: bool | None = None,
        level_colors: dict[str, str | tuple[int, int, int]] | None = None,
        colorize_message: bool = False,
    ) -> None:
        """Initialize colored console formatter.

        Args:
            fmt: Log format string (standard logging format).
            datefmt: Date format string.
            style: Format style ('%', '{', or '$').
            colorize: Force colorization on/off. If None, auto-detect.
            level_colors: Custom color mapping. Values can be:
                - ANSI color strings (e.g., ANSIColors.RED)
                - RGB tuples (e.g., (255, 0, 0))
                - Hex strings (e.g., "#FF0000" or "FF0000")
            colorize_message: If True, colorize entire message (not just level).

        Example:
                    # Custom color scheme with RGB/Hex colors
            from example_service.infra.logging import (
                ColoredConsoleFormatter,
                ANSIColors
            )

            custom_colors = {
                "DEBUG": (100, 150, 255),      # RGB tuple
                "INFO": "#00FF00",             # Hex string
                "WARNING": "FFA500",           # Hex without #
                "ERROR": ANSIColors.BRIGHT_RED + ANSIColors.BOLD,  # ANSI
            }

            formatter = ColoredConsoleFormatter(
                fmt='%(levelname)-8s | %(message)s',
                level_colors=custom_colors,
                colorize_message=True  # Color entire message
            )
        """
        super().__init__(fmt, datefmt, style)
        self._colorize = colorize
        self._level_colors_raw = level_colors or LEVEL_COLORS.copy()
        self._colorize_message = colorize_message
        self._color_support = ColorSupport()

        # Normalize level colors to ANSI escape codes
        self._level_colors: dict[str, str] = {}

    def _normalize_color(self, color: str | tuple[int, int, int], stream: Any) -> str:
        """Normalize a color value to an ANSI escape code.

        Args:
            color: Color value (ANSI string, RGB tuple, or hex string).
            stream: Output stream for terminal capability detection.

        Returns:
            ANSI escape code string.
        """
        # If already an ANSI string (starts with \033), return as-is
        if isinstance(color, str) and color.startswith("\033"):
            return color

        # If RGB tuple, convert to ANSI
        if isinstance(color, tuple) and len(color) == 3:
            return rgb_to_ansi(color, stream=stream)

        # If hex string, convert to ANSI
        if isinstance(color, str):
            try:
                return hex_to_ansi(color, stream=stream)
            except ValueError:
                # Not a valid hex color, assume it's an ANSI string
                return color

        # Fallback to empty string
        return ""

    def _get_normalized_colors(self, stream: Any) -> dict[str, str]:
        """Get level colors normalized to ANSI escape codes.

        Caches normalized colors per stream to avoid repeated conversions.

        Args:
            stream: Output stream for terminal capability detection.

        Returns:
            Dict mapping level names to ANSI escape codes.
        """
        # Use cached colors if available
        if self._level_colors:
            return self._level_colors

        # Normalize all level colors
        normalized: dict[str, str] = {}
        for level, color in self._level_colors_raw.items():
            normalized[level] = self._normalize_color(color, stream)

        # Cache for reuse
        self._level_colors = normalized
        return normalized

    def should_use_color(self, stream: Any) -> bool:
        """Determine if colors should be used for this stream.

        Args:
            stream: The output stream.

        Returns:
            True if colors should be used.
        """
        # If explicitly set, use that
        if self._colorize is not None:
            return self._colorize

        # Auto-detect based on stream
        return self._color_support.is_enabled(stream)

    def format(self, record: logging.LogRecord) -> str:
        """Format log record with colors if appropriate.

        Args:
            record: Log record to format.

        Returns:
            Formatted string with ANSI color codes if colors are enabled.
        """
        # Get the stream from the handler (if available)
        stream = getattr(record, "stream", sys.stderr)
        use_color = self.should_use_color(stream)

        if not use_color:
            # No color, use standard formatting
            return super().format(record)

        # Get normalized colors for this stream
        level_colors = self._get_normalized_colors(stream)

        # Save original level name
        original_levelname = record.levelname

        # Colorize level name
        level_color = level_colors.get(record.levelname, "")
        if level_color:
            record.levelname = f"{level_color}{record.levelname}{ANSIColors.RESET}"

        # Format the record
        formatted = super().format(record)

        # Restore original level name
        record.levelname = original_levelname

        # Colorize entire message if requested
        if self._colorize_message and level_color:
            formatted = f"{level_color}{formatted}{ANSIColors.RESET}"

        return formatted

    def formatException(
        self,
        ei: tuple[type[BaseException], BaseException, TracebackType | None]
        | tuple[None, None, None],
    ) -> str:
        """Format exception with colors.

        Args:
            ei: Exception info tuple.

        Returns:
            Formatted exception string (colored if appropriate).
        """
        exception_text = super().formatException(ei)

        # Get normalized colors and colorize exception (use ERROR color)
        stream = sys.stderr  # Exceptions usually go to stderr
        level_colors = self._get_normalized_colors(stream)
        error_color = level_colors.get("ERROR", ANSIColors.RED)
        return f"{error_color}{exception_text}{ANSIColors.RESET}"


class MinimalColoredFormatter(logging.Formatter):
    """Minimal colored formatter with just level colorization.

    Simpler than ColoredConsoleFormatter, only colorizes the level name
    without affecting the rest of the log message.

    Example:
            import logging
        from example_service.infra.logging import MinimalColoredFormatter

        handler = logging.StreamHandler()
        handler.setFormatter(MinimalColoredFormatter())

        logger = logging.getLogger(__name__)
        logger.addHandler(handler)

        logger.info("This message is not colored, but INFO is green")
    """

    def __init__(
        self,
        fmt: str | None = None,
        datefmt: str | None = None,
        style: Literal["%", "{", "$"] = "%",
        colorize: bool | None = None,
    ) -> None:
        """Initialize minimal colored formatter.

        Args:
            fmt: Log format string.
            datefmt: Date format string.
            style: Format style ('%', '{', or '$').
            colorize: Force colorization on/off. If None, auto-detect.
        """
        super().__init__(fmt, datefmt, style)
        self._colorize = colorize
        self._color_support = ColorSupport()

    def format(self, record: logging.LogRecord) -> str:
        """Format record with colored level name only.

        Args:
            record: Log record to format.

        Returns:
            Formatted string with colored level name.
        """
        # Determine if we should use color
        stream = getattr(record, "stream", sys.stderr)
        if self._colorize is None:
            use_color = self._color_support.is_enabled(stream)
        else:
            use_color = self._colorize

        if not use_color:
            return super().format(record)

        # Save and colorize level name
        original_levelname = record.levelname

        # Get color for this level (supports RGB/hex via LEVEL_COLORS)
        level_color_raw = LEVEL_COLORS.get(record.levelname, "")

        # If it's an RGB tuple or hex string, convert it
        if isinstance(level_color_raw, tuple):
            level_color = rgb_to_ansi(level_color_raw, stream=stream)
        elif isinstance(level_color_raw, str) and not level_color_raw.startswith("\033"):
            try:
                level_color = hex_to_ansi(level_color_raw, stream=stream)
            except ValueError:
                level_color = level_color_raw
        else:
            level_color = level_color_raw

        if level_color:
            record.levelname = f"{level_color}{record.levelname}{ANSIColors.RESET}"

        formatted = super().format(record)

        # Restore original
        record.levelname = original_levelname

        return formatted


def create_colored_handler(
    stream: Any = None,
    level: str = "DEBUG",
    fmt: str | None = None,
    colorize: bool | None = None,
    colorize_message: bool = False,
) -> logging.StreamHandler:
    """Create a StreamHandler with colored formatter.

    Convenience function for creating colored console handlers.

    Args:
        stream: Output stream (default: sys.stderr).
        level: Log level.
        fmt: Log format string.
        colorize: Force colorization on/off. If None, auto-detect.
        colorize_message: Colorize entire message (not just level).

    Returns:
        Configured StreamHandler with ColoredConsoleFormatter.

    Example:
            import logging
        from example_service.infra.logging import create_colored_handler

        # Create colored handler for development
        handler = create_colored_handler(
            level="DEBUG",
            fmt="%(asctime)s | %(levelname)-8s | %(message)s",
            colorize_message=True  # Color entire message
        )

        logger = logging.getLogger(__name__)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
    """
    if stream is None:
        stream = sys.stderr

    handler = logging.StreamHandler(stream)
    handler.setLevel(getattr(logging, level.upper()))

    if fmt is None:
        fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

    formatter = ColoredConsoleFormatter(
        fmt=fmt,
        datefmt="%Y-%m-%d %H:%M:%S",
        colorize=colorize,
        colorize_message=colorize_message,
    )

    handler.setFormatter(formatter)
    return handler
