"""Centralized color definitions for Clarvis.

Single source of truth for all colors used across Python and Swift.
Colors are defined with both ANSI 256 codes (for terminal) and RGB (for Swift).

Supports multiple retro themes:
- modern: Current bright colors (default)
- crt-amber: Classic amber phosphor CRT
- crt-green: Classic green phosphor CRT
- synthwave: 80s neon/Miami Vice aesthetic
- c64: Commodore 64 palette
- matrix: 90s hacker green-on-black
"""

from dataclasses import dataclass
from typing import Optional, Dict, List
from typing import Tuple


@dataclass(frozen=True)
class ColorDef:
    """Color definition with ANSI and RGB values."""
    ansi: int  # ANSI 256 color code
    rgb: Tuple[float, float, float]  # RGB values 0.0-1.0 for Swift

    @property
    def hex(self) -> str:
        """Get hex color string."""
        r, g, b = self.rgb
        return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"

    def ansi_fg(self) -> str:
        """Get ANSI foreground escape code."""
        return f"\033[38;5;{self.ansi}m"

    def ansi_bg(self) -> str:
        """Get ANSI background escape code."""
        return f"\033[48;5;{self.ansi}m"


# =============================================================================
# Theme Definitions
# =============================================================================

# Each theme maps status names to ColorDef instances
# Statuses: idle, resting, thinking, running, executing, awaiting, reading, writing, reviewing, offline
# Special: eureka, celebration (triggered on task completion), activated (wake word detected)

THEMES: dict[str, dict[str, ColorDef]] = {
    # Modern - current bright colors
    "modern": {
        "idle": ColorDef(8, (0.53, 0.53, 0.53)),
        "resting": ColorDef(8, (0.4, 0.4, 0.45)),
        "thinking": ColorDef(11, (1.0, 0.87, 0.0)),
        "running": ColorDef(10, (0.0, 1.0, 0.67)),
        "executing": ColorDef(208, (1.0, 0.5, 0.0)),      # orange - shell commands
        "awaiting": ColorDef(12, (0.4, 0.5, 1.0)),
        "reading": ColorDef(51, (0.0, 0.9, 0.9)),         # cyan - absorbing info
        "writing": ColorDef(207, (1.0, 0.4, 0.8)),        # pink/magenta - creative
        "reviewing": ColorDef(13, (1.0, 0.0, 1.0)),
        "offline": ColorDef(8, (0.53, 0.53, 0.53)),
        "eureka": ColorDef(220, (1.0, 0.85, 0.0)),        # bright gold - breakthrough!
        "celebration": ColorDef(214, (1.0, 0.7, 0.0)),    # warm gold - task complete!
        "activated": ColorDef(220, (1.0, 0.85, 0.2)),     # golden amber - activated/wake
        "listening": ColorDef(48, (0.2, 1.0, 0.6)),        # bright mint - actively listening
        "responding": ColorDef(117, (0.5, 0.7, 1.0)),      # soft blue - speaking response
    },

    # CRT Amber - classic amber phosphor terminal
    "crt-amber": {
        "idle": ColorDef(130, (0.6, 0.4, 0.0)),        # dim amber
        "resting": ColorDef(94, (0.5, 0.3, 0.0)),     # darker amber
        "thinking": ColorDef(214, (1.0, 0.7, 0.0)),   # bright amber
        "running": ColorDef(220, (1.0, 0.8, 0.2)),    # warm amber
        "executing": ColorDef(220, (1.0, 0.8, 0.2)),
        "awaiting": ColorDef(178, (0.8, 0.6, 0.1)),   # mid amber
        "reading": ColorDef(178, (0.8, 0.6, 0.1)),
        "writing": ColorDef(214, (1.0, 0.7, 0.0)),
        "reviewing": ColorDef(220, (1.0, 0.8, 0.2)),
        "offline": ColorDef(94, (0.4, 0.25, 0.0)),    # very dim amber
        "eureka": ColorDef(226, (1.0, 1.0, 0.3)),     # bright white-amber
        "celebration": ColorDef(226, (1.0, 1.0, 0.3)),
        "activated": ColorDef(226, (1.0, 1.0, 0.3)),  # bright amber
        "listening": ColorDef(214, (1.0, 0.7, 0.0)),    # warm amber - listening
        "responding": ColorDef(178, (0.8, 0.6, 0.1)),   # mid amber - speaking
    },

    # CRT Green - classic green phosphor terminal
    "crt-green": {
        "idle": ColorDef(22, (0.0, 0.5, 0.0)),        # dim green
        "resting": ColorDef(22, (0.0, 0.4, 0.0)),     # darker green
        "thinking": ColorDef(46, (0.0, 1.0, 0.0)),    # bright green
        "running": ColorDef(118, (0.5, 1.0, 0.2)),    # lime green
        "executing": ColorDef(118, (0.5, 1.0, 0.2)),
        "awaiting": ColorDef(34, (0.0, 0.7, 0.2)),    # mid green
        "reading": ColorDef(34, (0.0, 0.7, 0.2)),
        "writing": ColorDef(46, (0.0, 1.0, 0.0)),
        "reviewing": ColorDef(118, (0.5, 1.0, 0.2)),
        "offline": ColorDef(22, (0.0, 0.3, 0.0)),     # very dim green
        "eureka": ColorDef(156, (0.7, 1.0, 0.5)),     # bright lime
        "celebration": ColorDef(156, (0.7, 1.0, 0.5)),
        "activated": ColorDef(156, (0.7, 1.0, 0.5)),  # bright lime
        "listening": ColorDef(46, (0.0, 1.0, 0.0)),     # bright green - listening
        "responding": ColorDef(34, (0.0, 0.7, 0.2)),    # mid green - speaking
    },

    # Synthwave - 80s neon aesthetic
    "synthwave": {
        "idle": ColorDef(55, (0.4, 0.2, 0.6)),        # muted purple
        "resting": ColorDef(54, (0.3, 0.15, 0.5)),    # dark purple
        "thinking": ColorDef(199, (1.0, 0.2, 0.6)),   # hot pink
        "running": ColorDef(51, (0.0, 1.0, 1.0)),     # electric cyan
        "executing": ColorDef(208, (1.0, 0.5, 0.2)),  # neon orange
        "awaiting": ColorDef(33, (0.2, 0.4, 1.0)),    # electric blue
        "reading": ColorDef(51, (0.0, 1.0, 1.0)),     # electric cyan
        "writing": ColorDef(207, (1.0, 0.4, 0.8)),    # pink
        "reviewing": ColorDef(201, (1.0, 0.0, 1.0)),  # magenta
        "offline": ColorDef(54, (0.3, 0.15, 0.4)),    # dim purple
        "eureka": ColorDef(226, (1.0, 1.0, 0.4)),     # neon yellow
        "celebration": ColorDef(226, (1.0, 1.0, 0.4)),
        "activated": ColorDef(226, (1.0, 1.0, 0.4)),   # neon yellow
        "listening": ColorDef(51, (0.0, 1.0, 1.0)),     # electric cyan - listening
        "responding": ColorDef(207, (1.0, 0.4, 0.8)),   # pink - speaking
    },

    # C64 - Commodore 64 palette
    "c64": {
        "idle": ColorDef(250, (0.7, 0.7, 0.7)),       # light gray
        "resting": ColorDef(244, (0.5, 0.5, 0.5)),    # medium gray
        "thinking": ColorDef(117, (0.6, 0.7, 1.0)),   # light blue
        "running": ColorDef(71, (0.4, 0.8, 0.4)),     # green
        "executing": ColorDef(208, (0.9, 0.6, 0.2)),  # orange
        "awaiting": ColorDef(137, (0.6, 0.5, 0.3)),   # brown
        "reading": ColorDef(80, (0.4, 0.7, 0.7)),     # cyan
        "writing": ColorDef(98, (0.6, 0.5, 0.8)),     # purple
        "reviewing": ColorDef(168, (0.8, 0.5, 0.5)),  # light red
        "offline": ColorDef(240, (0.4, 0.4, 0.4)),    # dark gray
        "eureka": ColorDef(227, (1.0, 1.0, 0.5)),     # yellow
        "celebration": ColorDef(227, (1.0, 1.0, 0.5)),
        "activated": ColorDef(80, (0.4, 0.7, 0.7)),   # cyan
        "listening": ColorDef(71, (0.4, 0.8, 0.4)),     # green - listening
        "responding": ColorDef(117, (0.6, 0.7, 1.0)),   # light blue - speaking
    },

    # Matrix - 90s hacker aesthetic
    "matrix": {
        "idle": ColorDef(22, (0.0, 0.4, 0.0)),        # dark green
        "resting": ColorDef(22, (0.0, 0.3, 0.0)),     # darker green
        "thinking": ColorDef(46, (0.0, 1.0, 0.0)),    # bright green
        "running": ColorDef(118, (0.6, 1.0, 0.0)),    # lime
        "executing": ColorDef(118, (0.6, 1.0, 0.0)),
        "awaiting": ColorDef(35, (0.0, 0.8, 0.4)),    # teal green
        "reading": ColorDef(35, (0.0, 0.8, 0.4)),
        "writing": ColorDef(46, (0.0, 1.0, 0.0)),
        "reviewing": ColorDef(154, (0.7, 1.0, 0.3)),  # yellow-green
        "offline": ColorDef(22, (0.0, 0.25, 0.0)),    # very dark green
        "eureka": ColorDef(231, (1.0, 1.0, 1.0)),     # white flash
        "celebration": ColorDef(231, (1.0, 1.0, 1.0)),
        "activated": ColorDef(231, (1.0, 1.0, 1.0)),  # white flash
        "listening": ColorDef(46, (0.0, 1.0, 0.0)),     # bright green - listening
        "responding": ColorDef(35, (0.0, 0.8, 0.4)),    # teal green - speaking
    },
}

# Default theme
DEFAULT_THEME = "modern"

# Current active theme (set by load_theme)
_current_theme: str = DEFAULT_THEME


def get_available_themes() -> List[str]:
    """Get list of available theme names."""
    return list(THEMES.keys())


def load_theme(theme_name: str, overrides: Optional[Dict[str, List[float]]] = None) -> bool:
    """
    Load a theme by name with optional color overrides.

    Args:
        theme_name: Name of the base theme
        overrides: Optional dict mapping status names to [r, g, b] arrays

    Returns True if theme was loaded, False if theme doesn't exist.
    """
    global _current_theme, STATUS_MAP, _current_overrides

    if theme_name not in THEMES:
        return False

    _current_theme = theme_name
    _current_overrides = overrides or {}

    # Start with base theme
    STATUS_MAP = THEMES[theme_name].copy()

    # Apply overrides
    for status, rgb in _current_overrides.items():
        if status in STATUS_MAP and len(rgb) == 3:
            # Create new ColorDef with overridden RGB but same ANSI
            base_ansi = STATUS_MAP[status].ansi
            STATUS_MAP[status] = ColorDef(base_ansi, tuple(rgb))

    return True


# Current overrides (set by load_theme)
_current_overrides: dict[str, list[float]] = {}


def get_current_theme() -> str:
    """Get the name of the currently active theme."""
    return _current_theme


# =============================================================================
# Status Colors (uses current theme)
# =============================================================================

class StatusColors:
    """Maps status names to colors from current theme."""

    @classmethod
    def get(cls, status: str) -> ColorDef:
        """Get color for a status string."""
        return STATUS_MAP.get(status, STATUS_MAP.get("idle", ColorDef(8, (0.53, 0.53, 0.53))))


# Initialize STATUS_MAP with default theme
STATUS_MAP: dict[str, ColorDef] = THEMES[DEFAULT_THEME].copy()


# =============================================================================
# Config Export - For Swift/JSON
# =============================================================================

def get_status_colors_for_config() -> Dict[str, Dict]:
    """Get status colors in format suitable for config.json (uses current theme)."""
    return {
        status: {
            "r": color.rgb[0],
            "g": color.rgb[1],
            "b": color.rgb[2],
        }
        for status, color in STATUS_MAP.items()
    }


def get_merged_theme_colors(
    theme_name: str,
    overrides: Optional[Dict[str, List[float]]] = None
) -> Dict[str, List[float]]:
    """
    Get theme colors merged with overrides as RGB arrays.

    Args:
        theme_name: Name of the base theme
        overrides: Optional dict mapping status names to [r, g, b] arrays

    Returns:
        Dict mapping status names to [r, g, b] arrays
    """
    if theme_name not in THEMES:
        theme_name = DEFAULT_THEME

    overrides = overrides or {}
    result = {}

    for status, color in THEMES[theme_name].items():
        if status in overrides and len(overrides[status]) == 3:
            result[status] = overrides[status]
        else:
            result[status] = list(color.rgb)

    return result
