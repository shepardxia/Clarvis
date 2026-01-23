"""Centralized color definitions for Clarvis.

Single source of truth for all colors used across Python and Swift.
Colors are defined with both ANSI 256 codes (for terminal) and RGB (for Swift).
"""

from dataclasses import dataclass
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
# Base Palette
# =============================================================================

class Palette:
    """Base color palette."""
    # Neutrals
    BLACK = ColorDef(0, (0.0, 0.0, 0.0))
    GRAY = ColorDef(8, (0.53, 0.53, 0.53))
    DARK_GRAY = ColorDef(8, (0.4, 0.4, 0.45))
    WHITE = ColorDef(15, (1.0, 1.0, 1.0))

    # Primary colors
    YELLOW = ColorDef(11, (1.0, 0.87, 0.0))
    GREEN = ColorDef(10, (0.0, 1.0, 0.67))
    BLUE = ColorDef(12, (0.4, 0.5, 1.0))
    MAGENTA = ColorDef(13, (1.0, 0.0, 1.0))
    RED = ColorDef(9, (1.0, 0.33, 0.33))


# =============================================================================
# Status Colors
# =============================================================================

class StatusColors:
    """Maps status names to colors."""
    IDLE = Palette.GRAY
    RESTING = Palette.DARK_GRAY
    THINKING = Palette.YELLOW
    RUNNING = Palette.GREEN
    EXECUTING = Palette.GREEN
    AWAITING = Palette.BLUE
    READING = Palette.BLUE
    WRITING = Palette.BLUE
    REVIEWING = Palette.MAGENTA
    OFFLINE = Palette.GRAY

    @classmethod
    def get(cls, status: str) -> ColorDef:
        """Get color for a status string."""
        return STATUS_MAP.get(status, cls.IDLE)


# String-keyed lookup for runtime use
STATUS_MAP: dict[str, ColorDef] = {
    "idle": StatusColors.IDLE,
    "resting": StatusColors.RESTING,
    "thinking": StatusColors.THINKING,
    "running": StatusColors.RUNNING,
    "executing": StatusColors.EXECUTING,
    "awaiting": StatusColors.AWAITING,
    "reading": StatusColors.READING,
    "writing": StatusColors.WRITING,
    "reviewing": StatusColors.REVIEWING,
    "offline": StatusColors.OFFLINE,
}


# =============================================================================
# Legacy Compatibility - ANSI codes for existing code
# =============================================================================

# Simple dict of name -> ANSI code (for renderer.py)
ANSI_COLORS = {
    "gray": Palette.GRAY.ansi,
    "white": Palette.WHITE.ansi,
    "yellow": Palette.YELLOW.ansi,
    "green": Palette.GREEN.ansi,
    "blue": Palette.BLUE.ansi,
    "magenta": Palette.MAGENTA.ansi,
}

# Status -> ANSI code (for renderer.py)
STATUS_ANSI = {status: color.ansi for status, color in STATUS_MAP.items()}


# =============================================================================
# Config Export - For Swift/JSON
# =============================================================================

def get_status_colors_for_config() -> dict[str, dict]:
    """Get status colors in format suitable for config.json."""
    return {
        status: {
            "r": color.rgb[0],
            "g": color.rgb[1],
            "b": color.rgb[2],
        }
        for status, color in STATUS_MAP.items()
    }
