"""Terminal color capability detection and management.

Detects whether terminal supports 16 colors, 256 colors, or 24-bit truecolor,
and provides appropriate ANSI escape sequences for each mode.
"""

from __future__ import annotations

from enum import IntEnum
import os
import sys
from typing import TextIO


class ColorMode(IntEnum):
    """Terminal color capability levels.

    Values are ordered by capability (higher = more colors).
    """

    NO_COLOR = 0  # No colors (disabled or unsupported)
    ANSI_16 = 1  # 16 basic ANSI colors
    ANSI_256 = 2  # 256-color palette
    TRUECOLOR = 3  # 24-bit RGB (16.7 million colors)


def detect_color_mode(stream: TextIO | None = None) -> ColorMode:
    """Detect terminal color capabilities.

    Checks environment variables and terminal properties to determine
    the maximum color mode supported by the terminal.

    Args:
        stream: Stream to check (default: sys.stderr).

    Returns:
        ColorMode enum indicating maximum supported colors.

    Environment Variables (in order of precedence):
        - FORCE_COLOR: Force specific color mode (0-3)
        - NO_COLOR: Disable colors completely
        - COLORTERM: Indicates truecolor support ("truecolor" or "24bit")
        - TERM: Terminal type (e.g., "xterm-256color")

    Example:
            from example_service.infra.logging.color_modes import detect_color_mode

        mode = detect_color_mode()
        if mode >= ColorMode.ANSI_256:
            print("Terminal supports 256 colors!")
    """
    if stream is None:
        stream = sys.stderr

    # Check FORCE_COLOR environment variable (highest priority)
    force_color = os.getenv("FORCE_COLOR", "").strip()
    if force_color:
        if force_color == "0":
            return ColorMode.NO_COLOR
        if force_color == "1":
            return ColorMode.ANSI_16
        if force_color == "2":
            return ColorMode.ANSI_256
        if force_color.isdigit() and int(force_color) >= 3:
            return ColorMode.TRUECOLOR

    # Check NO_COLOR (per spec: https://no-color.org/)
    if os.getenv("NO_COLOR"):
        return ColorMode.NO_COLOR

    # Check if stream is a TTY
    try:
        if not stream.isatty():
            return ColorMode.NO_COLOR
    except Exception:
        return ColorMode.NO_COLOR

    # Check COLORTERM for truecolor support
    colorterm = os.getenv("COLORTERM", "").lower()
    if colorterm in ("truecolor", "24bit"):
        return ColorMode.TRUECOLOR

    # Check TERM environment variable
    term = os.getenv("TERM", "").lower()

    # Dumb terminal doesn't support colors
    if term == "dumb":
        return ColorMode.NO_COLOR

    # Check for 256-color support
    if "256color" in term or "256" in term:
        return ColorMode.ANSI_256

    # Check for truecolor terminal emulators
    truecolor_terms = [
        "iterm",
        "kitty",
        "alacritty",
        "wezterm",
        "rio",
        "ghostty",
    ]
    if any(t in term for t in truecolor_terms):
        return ColorMode.TRUECOLOR

    # Check for common terminal emulators with good color support
    modern_terms = [
        "xterm",
        "vt100",
        "vt220",
        "rxvt",
        "screen",
        "tmux",
        "konsole",
        "gnome",
    ]
    if any(t in term for t in modern_terms):
        # Most modern terminals support at least 256 colors
        return ColorMode.ANSI_256

    # Check if we're in CI environment (usually supports at least 16 colors)
    if os.getenv("CI") and any(
        ci in os.environ
        for ci in [
            "GITHUB_ACTIONS",
            "GITLAB_CI",
            "CIRCLECI",
            "TRAVIS",
            "JENKINS",
        ]
    ):
        return ColorMode.ANSI_16

    # Windows Terminal and ConEmu support truecolor
    if os.name == "nt":
        wt_session = os.getenv("WT_SESSION")
        if wt_session:  # Windows Terminal
            return ColorMode.TRUECOLOR
        if "ConEmu" in os.getenv("CONEMUANSI", ""):
            return ColorMode.TRUECOLOR

    # Default to basic 16 colors if we can't determine better
    return ColorMode.ANSI_16


class ColorModeManager:
    """Manages color mode detection and caching.

    Caches detection results per stream to avoid repeated checks.
    """

    def __init__(self) -> None:
        """Initialize color mode manager."""
        self._cached_modes: dict[int, ColorMode] = {}
        self._forced_mode: ColorMode | None = None

    def get_mode(self, stream: TextIO | None = None) -> ColorMode:
        """Get color mode for stream (cached).

        Args:
            stream: Stream to check (default: sys.stderr).

        Returns:
            ColorMode enum indicating supported colors.
        """
        # If mode is forced, return that
        if self._forced_mode is not None:
            return self._forced_mode

        if stream is None:
            stream = sys.stderr

        # Check cache
        stream_id = id(stream)
        if stream_id not in self._cached_modes:
            self._cached_modes[stream_id] = detect_color_mode(stream)

        return self._cached_modes[stream_id]

    def force_mode(self, mode: ColorMode) -> None:
        """Force a specific color mode for all streams.

        Args:
            mode: Color mode to force.

        Example:
                    from example_service.infra.logging.color_modes import (
                color_mode_manager,
                ColorMode
            )

            # Force 256-color mode
            color_mode_manager.force_mode(ColorMode.ANSI_256)
        """
        self._forced_mode = mode
        self.clear_cache()

    def clear_cache(self) -> None:
        """Clear cached color mode results.

        Call this if environment changes at runtime.
        """
        self._cached_modes.clear()


# Global color mode manager
color_mode_manager = ColorModeManager()


def get_color_mode(stream: TextIO | None = None) -> ColorMode:
    """Get color mode for stream (cached, global).

    Args:
        stream: Stream to check (default: sys.stderr).

    Returns:
        ColorMode indicating supported colors.

    Example:
            from example_service.infra.logging.color_modes import (
            get_color_mode,
            ColorMode
        )
        import sys

        mode = get_color_mode(sys.stderr)
        if mode >= ColorMode.TRUECOLOR:
            print("Full RGB colors available!")
    """
    return color_mode_manager.get_mode(stream)


def supports_color(mode: ColorMode, minimum: ColorMode = ColorMode.ANSI_16) -> bool:
    """Check if color mode meets minimum requirement.

    Args:
        mode: Current color mode.
        minimum: Minimum required mode.

    Returns:
        True if mode >= minimum.

    Example:
            from example_service.infra.logging.color_modes import (
            get_color_mode,
            supports_color,
            ColorMode
        )

        mode = get_color_mode()
        if supports_color(mode, ColorMode.ANSI_256):
            print("Can use 256 colors!")
    """
    return mode >= minimum
