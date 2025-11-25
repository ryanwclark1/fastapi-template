"""RGB/Hex to ANSI color conversion utilities.

Converts RGB tuples and hex color strings to appropriate ANSI escape codes
based on terminal capabilities (16-color, 256-color, or truecolor).
"""

from __future__ import annotations

import re
from typing import TextIO

from example_service.infra.logging.color_modes import ColorMode, get_color_mode

# ──────────────────────────────────────────────────────────────
# ANSI 16-color palette (standard terminal colors)
# ──────────────────────────────────────────────────────────────

ANSI_16_PALETTE: list[tuple[int, int, int]] = [
    # Normal colors (30-37)
    (0, 0, 0),  # Black
    (128, 0, 0),  # Red
    (0, 128, 0),  # Green
    (128, 128, 0),  # Yellow
    (0, 0, 128),  # Blue
    (128, 0, 128),  # Magenta
    (0, 128, 128),  # Cyan
    (192, 192, 192),  # White
    # Bright colors (90-97)
    (128, 128, 128),  # Bright Black (Gray)
    (255, 0, 0),  # Bright Red
    (0, 255, 0),  # Bright Green
    (255, 255, 0),  # Bright Yellow
    (0, 0, 255),  # Bright Blue
    (255, 0, 255),  # Bright Magenta
    (0, 255, 255),  # Bright Cyan
    (255, 255, 255),  # Bright White
]


# ──────────────────────────────────────────────────────────────
# ANSI 256-color palette
# ──────────────────────────────────────────────────────────────


def _build_256_palette() -> list[tuple[int, int, int]]:
    """Build the standard 256-color palette.

    The 256-color palette consists of:
    - Colors 0-15: Same as 16-color palette
    - Colors 16-231: 6x6x6 RGB cube
    - Colors 232-255: Grayscale ramp
    """
    palette = ANSI_16_PALETTE.copy()

    # 6x6x6 RGB cube (colors 16-231)
    for r in range(6):
        for g in range(6):
            for b in range(6):
                # Map 0-5 to 0, 95, 135, 175, 215, 255
                rgb = (
                    0 if r == 0 else 55 + r * 40,
                    0 if g == 0 else 55 + g * 40,
                    0 if b == 0 else 55 + b * 40,
                )
                palette.append(rgb)

    # Grayscale ramp (colors 232-255)
    for i in range(24):
        gray = 8 + i * 10
        palette.append((gray, gray, gray))

    return palette


ANSI_256_PALETTE = _build_256_palette()


# ──────────────────────────────────────────────────────────────
# Color distance and nearest color
# ──────────────────────────────────────────────────────────────


def _color_distance(c1: tuple[int, int, int], c2: tuple[int, int, int]) -> float:
    """Calculate Euclidean distance between two RGB colors.

    Args:
        c1: First RGB color (r, g, b).
        c2: Second RGB color (r, g, b).

    Returns:
        Euclidean distance in RGB space.
    """
    return ((c1[0] - c2[0]) ** 2 + (c1[1] - c2[1]) ** 2 + (c1[2] - c2[2]) ** 2) ** 0.5


def _nearest_color_index(
    rgb: tuple[int, int, int], palette: list[tuple[int, int, int]]
) -> int:
    """Find the index of the nearest color in the palette.

    Args:
        rgb: Target RGB color (r, g, b).
        palette: List of RGB colors to search.

    Returns:
        Index of the nearest color in the palette.
    """
    min_distance = float("inf")
    nearest_idx = 0

    for idx, palette_color in enumerate(palette):
        distance = _color_distance(rgb, palette_color)
        if distance < min_distance:
            min_distance = distance
            nearest_idx = idx

    return nearest_idx


# ──────────────────────────────────────────────────────────────
# Hex parsing
# ──────────────────────────────────────────────────────────────

# Hex color regex: #RGB, #RRGGBB, RGB, RRGGBB (case-insensitive)
HEX_COLOR_PATTERN = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert hex color string to RGB tuple.

    Supports formats:
    - #RGB (3-digit, shorthand)
    - #RRGGBB (6-digit)
    - RGB (without #)
    - RRGGBB (without #)

    Args:
        hex_color: Hex color string (e.g., "#FF5733", "F73", "#abc").

    Returns:
        RGB tuple (r, g, b) with values 0-255.

    Raises:
        ValueError: If hex_color is not a valid hex color string.

    Example:
        >>> hex_to_rgb("#FF5733")
        (255, 87, 51)
        >>> hex_to_rgb("abc")
        (170, 187, 204)
        >>> hex_to_rgb("#F73")
        (255, 119, 51)
    """
    match = HEX_COLOR_PATTERN.match(hex_color)
    if not match:
        raise ValueError(f"Invalid hex color: {hex_color}")

    hex_digits = match.group(1)

    # Handle 3-digit shorthand (#RGB -> #RRGGBB)
    if len(hex_digits) == 3:
        hex_digits = "".join(c * 2 for c in hex_digits)

    # Parse RGB components
    r = int(hex_digits[0:2], 16)
    g = int(hex_digits[2:4], 16)
    b = int(hex_digits[4:6], 16)

    return (r, g, b)


# ──────────────────────────────────────────────────────────────
# ANSI escape code generation
# ──────────────────────────────────────────────────────────────


def rgb_to_ansi_16(rgb: tuple[int, int, int]) -> str:
    """Convert RGB color to 16-color ANSI escape code.

    Finds the nearest color in the standard 16-color palette.

    Args:
        rgb: RGB tuple (r, g, b) with values 0-255.

    Returns:
        ANSI escape code string (e.g., "\\033[31m" for red).

    Example:
        >>> rgb_to_ansi_16((255, 0, 0))
        '\\033[91m'  # Bright red
        >>> rgb_to_ansi_16((128, 0, 0))
        '\\033[31m'  # Red
    """
    nearest_idx = _nearest_color_index(rgb, ANSI_16_PALETTE)

    # Map index to ANSI code
    # 0-7: normal colors (30-37)
    # 8-15: bright colors (90-97)
    if nearest_idx < 8:
        return f"\033[{30 + nearest_idx}m"
    else:
        return f"\033[{90 + (nearest_idx - 8)}m"


def rgb_to_ansi_256(rgb: tuple[int, int, int]) -> str:
    """Convert RGB color to 256-color ANSI escape code.

    Finds the nearest color in the 256-color palette.

    Args:
        rgb: RGB tuple (r, g, b) with values 0-255.

    Returns:
        ANSI escape code string (e.g., "\\033[38;5;196m" for red).

    Example:
        >>> rgb_to_ansi_256((255, 0, 0))
        '\\033[38;5;196m'  # Bright red
    """
    nearest_idx = _nearest_color_index(rgb, ANSI_256_PALETTE)
    return f"\033[38;5;{nearest_idx}m"


def rgb_to_ansi_truecolor(rgb: tuple[int, int, int]) -> str:
    """Convert RGB color to 24-bit truecolor ANSI escape code.

    Args:
        rgb: RGB tuple (r, g, b) with values 0-255.

    Returns:
        ANSI escape code string (e.g., "\\033[38;2;255;0;0m" for pure red).

    Example:
        >>> rgb_to_ansi_truecolor((255, 87, 51))
        '\\033[38;2;255;87;51m'
    """
    r, g, b = rgb
    return f"\033[38;2;{r};{g};{b}m"


# ──────────────────────────────────────────────────────────────
# Adaptive color conversion
# ──────────────────────────────────────────────────────────────


def rgb_to_ansi(
    rgb: tuple[int, int, int],
    mode: ColorMode | None = None,
    stream: TextIO | None = None,
) -> str:
    """Convert RGB color to ANSI escape code based on terminal capability.

    Automatically detects terminal capabilities and uses the best available
    color mode. Falls back to simpler modes if needed.

    Args:
        rgb: RGB tuple (r, g, b) with values 0-255.
        mode: Color mode to use. If None, auto-detect from stream.
        stream: Stream to check for color support (default: sys.stderr).

    Returns:
        ANSI escape code string appropriate for the terminal.

    Example:
        >>> rgb_to_ansi((255, 87, 51))  # Auto-detect
        '\\033[38;2;255;87;51m'  # On truecolor terminal
        >>> rgb_to_ansi((255, 87, 51), mode=ColorMode.ANSI_16)
        '\\033[91m'  # Forced to 16-color
    """
    if mode is None:
        mode = get_color_mode(stream)

    if mode >= ColorMode.TRUECOLOR:
        return rgb_to_ansi_truecolor(rgb)
    elif mode >= ColorMode.ANSI_256:
        return rgb_to_ansi_256(rgb)
    elif mode >= ColorMode.ANSI_16:
        return rgb_to_ansi_16(rgb)
    else:
        return ""  # NO_COLOR mode


def hex_to_ansi(
    hex_color: str,
    mode: ColorMode | None = None,
    stream: TextIO | None = None,
) -> str:
    """Convert hex color to ANSI escape code based on terminal capability.

    Automatically detects terminal capabilities and uses the best available
    color mode. Falls back to simpler modes if needed.

    Args:
        hex_color: Hex color string (e.g., "#FF5733", "F73", "#abc").
        mode: Color mode to use. If None, auto-detect from stream.
        stream: Stream to check for color support (default: sys.stderr).

    Returns:
        ANSI escape code string appropriate for the terminal.

    Raises:
        ValueError: If hex_color is not a valid hex color string.

    Example:
        >>> hex_to_ansi("#FF5733")  # Auto-detect
        '\\033[38;2;255;87;51m'  # On truecolor terminal
        >>> hex_to_ansi("#FF5733", mode=ColorMode.ANSI_16)
        '\\033[91m'  # Forced to 16-color
    """
    rgb = hex_to_rgb(hex_color)
    return rgb_to_ansi(rgb, mode, stream)


# ──────────────────────────────────────────────────────────────
# Background colors
# ──────────────────────────────────────────────────────────────


def rgb_to_ansi_bg_16(rgb: tuple[int, int, int]) -> str:
    """Convert RGB color to 16-color ANSI background escape code.

    Args:
        rgb: RGB tuple (r, g, b) with values 0-255.

    Returns:
        ANSI background escape code string (e.g., "\\033[41m" for red background).
    """
    nearest_idx = _nearest_color_index(rgb, ANSI_16_PALETTE)

    if nearest_idx < 8:
        return f"\033[{40 + nearest_idx}m"
    else:
        return f"\033[{100 + (nearest_idx - 8)}m"


def rgb_to_ansi_bg_256(rgb: tuple[int, int, int]) -> str:
    """Convert RGB color to 256-color ANSI background escape code.

    Args:
        rgb: RGB tuple (r, g, b) with values 0-255.

    Returns:
        ANSI background escape code string (e.g., "\\033[48;5;196m").
    """
    nearest_idx = _nearest_color_index(rgb, ANSI_256_PALETTE)
    return f"\033[48;5;{nearest_idx}m"


def rgb_to_ansi_bg_truecolor(rgb: tuple[int, int, int]) -> str:
    """Convert RGB color to 24-bit truecolor ANSI background escape code.

    Args:
        rgb: RGB tuple (r, g, b) with values 0-255.

    Returns:
        ANSI background escape code string (e.g., "\\033[48;2;255;0;0m").
    """
    r, g, b = rgb
    return f"\033[48;2;{r};{g};{b}m"


def rgb_to_ansi_bg(
    rgb: tuple[int, int, int],
    mode: ColorMode | None = None,
    stream: TextIO | None = None,
) -> str:
    """Convert RGB color to ANSI background escape code based on terminal capability.

    Args:
        rgb: RGB tuple (r, g, b) with values 0-255.
        mode: Color mode to use. If None, auto-detect from stream.
        stream: Stream to check for color support (default: sys.stderr).

    Returns:
        ANSI background escape code string appropriate for the terminal.
    """
    if mode is None:
        mode = get_color_mode(stream)

    if mode >= ColorMode.TRUECOLOR:
        return rgb_to_ansi_bg_truecolor(rgb)
    elif mode >= ColorMode.ANSI_256:
        return rgb_to_ansi_bg_256(rgb)
    elif mode >= ColorMode.ANSI_16:
        return rgb_to_ansi_bg_16(rgb)
    else:
        return ""


def hex_to_ansi_bg(
    hex_color: str,
    mode: ColorMode | None = None,
    stream: TextIO | None = None,
) -> str:
    """Convert hex color to ANSI background escape code based on terminal capability.

    Args:
        hex_color: Hex color string (e.g., "#FF5733", "F73", "#abc").
        mode: Color mode to use. If None, auto-detect from stream.
        stream: Stream to check for color support (default: sys.stderr).

    Returns:
        ANSI background escape code string appropriate for the terminal.

    Raises:
        ValueError: If hex_color is not a valid hex color string.
    """
    rgb = hex_to_rgb(hex_color)
    return rgb_to_ansi_bg(rgb, mode, stream)
