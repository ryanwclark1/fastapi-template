"""ANSI color support for console logging.

Provides environment-aware colorization for console logs with automatic
detection of terminal capabilities and respect for NO_COLOR/FORCE_COLOR.

Inspired by loguru's colorization but simpler and more maintainable.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import TextIO

logger = logging.getLogger(__name__)


class ANSIColors:
    """ANSI escape codes for terminal colors and styles.

    Based on ANSI SGR (Select Graphic Rendition) codes.
    Reference: https://en.wikipedia.org/wiki/ANSI_escape_code
    """

    # Reset
    RESET = "\033[0m"

    # Styles
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"

    # Foreground colors (standard)
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    # Foreground colors (bright)
    BRIGHT_BLACK = "\033[90m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"

    # Aliases
    GRAY = BRIGHT_BLACK
    GREY = BRIGHT_BLACK


def should_colorize(stream: TextIO | None) -> bool:
    """Determine if colorization should be enabled for a stream.

    Implements color detection logic inspired by loguru's _colorama.py.
    Respects NO_COLOR and FORCE_COLOR environment variables per spec.

    Args:
        stream: The stream to check (sys.stdout, sys.stderr, etc.).

    Returns:
        True if colors should be used, False otherwise.

    Checks (in order):
        1. NO_COLOR env var (https://no-color.org/)
        2. FORCE_COLOR env var (https://force-color.org/)
        3. CI environment detection
        4. Terminal capability (isatty())

    Example:
            import sys
        from example_service.infra.logging.colors import should_colorize

        if should_colorize(sys.stderr):
            print("Colors enabled!")

    Environment Variables:
        - NO_COLOR: If set to non-empty string, disables colors
        - FORCE_COLOR: If set to non-empty string, forces colors
        - CI: Common CI environment variable
        - TRAVIS, CIRCLECI, GITHUB_ACTIONS, etc.: CI-specific vars
    """
    if stream is None:
        return False

    is_standard_stream = stream is sys.stdout or stream is sys.stderr
    is_original_standard_stream = stream is sys.__stdout__ or stream is sys.__stderr__

    if is_standard_stream or is_original_standard_stream:
        # Per the spec (https://no-color.org/), check for non-empty string
        if os.getenv("NO_COLOR"):
            return False

        # Per the spec (https://force-color.org/), check for non-empty string
        if os.getenv("FORCE_COLOR"):
            return True

    # Check for Jupyter/IPython environments
    if is_standard_stream:
        try:
            import builtins

            if getattr(builtins, "__IPYTHON__", False):
                return True
        except Exception as e:
            # Log expected import errors at debug level, fall through to other checks
            logger.debug("Failed to check for IPython environment: %s", e, exc_info=True)

    # Check for CI environments (most support colors)
    if is_original_standard_stream:
        if "CI" in os.environ and any(
            ci in os.environ
            for ci in [
                "TRAVIS",
                "CIRCLECI",
                "APPVEYOR",
                "GITLAB_CI",
                "GITHUB_ACTIONS",
                "JENKINS",
            ]
        ):
            return True

        # PyCharm terminal supports colors
        if "PYCHARM_HOSTED" in os.environ:
            return True

        # Dumb terminal doesn't support colors
        if os.environ.get("TERM", "") == "dumb":
            return False

        # Windows with TERM set usually supports colors
        if os.name == "nt" and "TERM" in os.environ:
            return True

    # Check if stream is a TTY (interactive terminal)
    try:
        return stream.isatty()
    except Exception:
        return False


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text.

    Args:
        text: Text potentially containing ANSI codes.

    Returns:
        Text with all ANSI codes removed.

    Example:
            from example_service.infra.logging.colors import strip_ansi, ANSIColors

        colored = f"{ANSIColors.RED}Error{ANSIColors.RESET}"
        plain = strip_ansi(colored)  # "Error"
    """
    import re

    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    return ansi_escape.sub("", text)


# Level-based color mapping (default scheme)
LEVEL_COLORS: dict[str, str] = {
    "TRACE": ANSIColors.BRIGHT_BLACK,
    "DEBUG": ANSIColors.CYAN,
    "INFO": ANSIColors.GREEN,
    "SUCCESS": ANSIColors.BRIGHT_GREEN,
    "WARNING": ANSIColors.YELLOW,
    "ERROR": ANSIColors.RED,
    "CRITICAL": ANSIColors.BRIGHT_RED + ANSIColors.BOLD,
}


def colorize_level(level_name: str, use_color: bool = True) -> str:
    """Colorize a log level name.

    Args:
        level_name: Log level name (DEBUG, INFO, ERROR, etc.).
        use_color: Whether to apply color.

    Returns:
        Colorized level name with ANSI codes (or plain if use_color=False).

    Example:
            from example_service.infra.logging.colors import colorize_level

        colored = colorize_level("ERROR")  # Red "ERROR"
        plain = colorize_level("ERROR", use_color=False)  # Plain "ERROR"
    """
    if not use_color:
        return level_name

    color = LEVEL_COLORS.get(level_name, "")
    if color:
        return f"{color}{level_name}{ANSIColors.RESET}"
    return level_name


def colorize_message(message: str, level_name: str, use_color: bool = True) -> str:
    """Colorize entire log message based on level.

    Args:
        message: Log message.
        level_name: Log level name.
        use_color: Whether to apply color.

    Returns:
        Colorized message (or plain if use_color=False).

    Example:
            from example_service.infra.logging.colors import colorize_message

        colored = colorize_message("Something failed", "ERROR")
        # Returns red text
    """
    if not use_color:
        return message

    color = LEVEL_COLORS.get(level_name, "")
    if color:
        return f"{color}{message}{ANSIColors.RESET}"
    return message


class ColorSupport:
    """Helper class to manage color support state.

    Caches color detection results to avoid repeated checks.
    """

    def __init__(self) -> None:
        """Initialize color support manager."""
        self._cached_results: dict[int, bool] = {}

    def is_enabled(self, stream: TextIO | None) -> bool:
        """Check if colors are enabled for a stream (cached).

        Args:
            stream: Stream to check.

        Returns:
            True if colors should be used.
        """
        if stream is None:
            return False

        stream_id = id(stream)
        if stream_id not in self._cached_results:
            self._cached_results[stream_id] = should_colorize(stream)

        return self._cached_results[stream_id]

    def clear_cache(self) -> None:
        """Clear cached color detection results.

        Useful if environment changes during runtime.
        """
        self._cached_results.clear()


# Global color support manager
_color_support = ColorSupport()


def is_color_enabled(stream: TextIO | None = None) -> bool:
    """Check if colors are enabled (cached, global).

    Args:
        stream: Stream to check. If None, checks sys.stderr.

    Returns:
        True if colors should be used.

    Example:
            import sys
        from example_service.infra.logging.colors import is_color_enabled

        if is_color_enabled(sys.stderr):
            # Use colors
            pass
    """
    if stream is None:
        stream = sys.stderr
    return _color_support.is_enabled(stream)


def clear_color_cache() -> None:
    """Clear color detection cache.

    Call this if environment variables change at runtime.

    Example:
            import os
        from example_service.infra.logging.colors import clear_color_cache

        os.environ["NO_COLOR"] = "1"
        clear_color_cache()  # Force re-detection
    """
    _color_support.clear_cache()
