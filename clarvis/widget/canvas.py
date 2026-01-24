#!/usr/bin/env python3
"""
Canvas and brush system for pixel-art rendering.

Core design:
- Canvas: 2D grid of (char, color) cells
- Brush: Functions that paint onto a canvas
- Sprite: Pre-built character patterns
- Compositor: Layers multiple canvases

Block character reference:
  Full:    █ (U+2588)
  Halves:  ▀ (upper) ▄ (lower) ▌ (left) ▐ (right)
  Corners: ▛ (UL) ▜ (UR) ▙ (LL) ▟ (LR)
  Quads:   ▘ (UL) ▝ (UR) ▖ (LL) ▗ (LR)
  Shades:  ░ (light) ▒ (medium) ▓ (dark)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional


# =============================================================================
# Colors (Canvas-local enum for Cell rendering)
# =============================================================================

class Color(Enum):
    """ANSI 256-color codes for canvas cells. Value is the color number."""
    RESET = -1

    # Basic colors
    BLACK = 0
    RED = 1
    GREEN = 2
    YELLOW = 3
    BLUE = 4
    MAGENTA = 5
    WHITE = 7

    # Bright colors
    GRAY = 8
    BRIGHT_RED = 9
    BRIGHT_GREEN = 10
    BRIGHT_YELLOW = 11
    BRIGHT_BLUE = 12
    BRIGHT_MAGENTA = 13
    BRIGHT_WHITE = 15

    def ansi_fg(self) -> str:
        """Get ANSI foreground escape code."""
        if self == Color.RESET:
            return "\033[0m"
        return f"\033[38;5;{self.value}m"

    def ansi_bg(self) -> str:
        """Get ANSI background escape code."""
        if self == Color.RESET:
            return "\033[0m"
        return f"\033[48;5;{self.value}m"


# Note: Status colors are defined centrally in core.colors
# Import from there: from clarvis.core.colors import STATUS_MAP


# =============================================================================
# Cell and Canvas
# =============================================================================

@dataclass
class Cell:
    """A single canvas cell with character and color."""
    char: str = " "
    fg: Color = Color.WHITE
    bg: Optional[Color] = None

    def render(self) -> str:
        """Render cell to ANSI string."""
        parts = []
        if self.bg:
            parts.append(self.bg.ansi_bg())
        parts.append(self.fg.ansi_fg())
        parts.append(self.char)
        parts.append(Color.RESET.ansi_fg())
        return "".join(parts)


class Canvas:
    """2D grid of cells for drawing."""

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.cells: list[list[Cell]] = [
            [Cell() for _ in range(width)] for _ in range(height)
        ]

    def __getitem__(self, pos: tuple[int, int]) -> Cell:
        x, y = pos
        if 0 <= x < self.width and 0 <= y < self.height:
            return self.cells[y][x]
        return Cell()  # Out of bounds returns empty cell

    def __setitem__(self, pos: tuple[int, int], cell: Cell):
        x, y = pos
        if 0 <= x < self.width and 0 <= y < self.height:
            self.cells[y][x] = cell

    def put(self, x: int, y: int, char: str, fg: Color = Color.WHITE, bg: Optional[Color] = None):
        """Put a single character at position."""
        if 0 <= x < self.width and 0 <= y < self.height:
            self.cells[y][x] = Cell(char, fg, bg)

    def fill(self, x: int, y: int, w: int, h: int, char: str = " ", fg: Color = Color.WHITE):
        """Fill a rectangle with a character."""
        for dy in range(h):
            for dx in range(w):
                self.put(x + dx, y + dy, char, fg)

    def clear(self):
        """Clear the canvas."""
        for y in range(self.height):
            for x in range(self.width):
                self.cells[y][x] = Cell()

    def composite(self, other: "Canvas", ox: int, oy: int, transparent: str = " "):
        """Composite another canvas onto this one. Transparent char is skipped."""
        for y in range(other.height):
            for x in range(other.width):
                cell = other[x, y]
                if cell.char != transparent:
                    self.put(ox + x, oy + y, cell.char, cell.fg, cell.bg)

    def render(self) -> str:
        """Render canvas to ANSI string."""
        lines = []
        for row in self.cells:
            line = "".join(cell.render() for cell in row)
            lines.append(line)
        return "\n".join(lines)

    def render_plain(self) -> str:
        """Render canvas without colors (plain text)."""
        lines = []
        for row in self.cells:
            line = "".join(cell.char for cell in row)
            lines.append(line)
        return "\n".join(lines)


# =============================================================================
# Brushes - Drawing Primitives
# =============================================================================

class Brush:
    """Collection of drawing primitives (static methods that paint onto canvas)."""

    # Block characters for reference
    FULL = "█"
    HALF_TOP = "▀"
    HALF_BOTTOM = "▄"
    HALF_LEFT = "▌"
    HALF_RIGHT = "▐"
    CORNER_UL = "▛"
    CORNER_UR = "▜"
    CORNER_LL = "▙"
    CORNER_LR = "▟"
    QUAD_UL = "▘"
    QUAD_UR = "▝"
    QUAD_LL = "▖"
    QUAD_LR = "▗"
    SHADE_LIGHT = "░"
    SHADE_MED = "▒"
    SHADE_DARK = "▓"

    @staticmethod
    def point(canvas: Canvas, x: int, y: int, char: str = "█", color: Color = Color.WHITE):
        """Draw a single point."""
        canvas.put(x, y, char, color)

    @staticmethod
    def hline(canvas: Canvas, x: int, y: int, length: int, char: str = "─", color: Color = Color.WHITE):
        """Draw a horizontal line."""
        for i in range(length):
            canvas.put(x + i, y, char, color)

    @staticmethod
    def vline(canvas: Canvas, x: int, y: int, length: int, char: str = "│", color: Color = Color.WHITE):
        """Draw a vertical line."""
        for i in range(length):
            canvas.put(x, y + i, char, color)

    @staticmethod
    def rect(canvas: Canvas, x: int, y: int, w: int, h: int, char: str = "█", color: Color = Color.WHITE):
        """Draw a filled rectangle."""
        for dy in range(h):
            for dx in range(w):
                canvas.put(x + dx, y + dy, char, color)

    @staticmethod
    def rect_outline(canvas: Canvas, x: int, y: int, w: int, h: int, color: Color = Color.WHITE,
                     h_char: str = "─", v_char: str = "│",
                     corners: tuple[str, str, str, str] = ("┌", "┐", "└", "┘")):
        """Draw a rectangle outline with box-drawing characters."""
        tl, tr, bl, br = corners

        # Top and bottom
        canvas.put(x, y, tl, color)
        canvas.put(x + w - 1, y, tr, color)
        canvas.put(x, y + h - 1, bl, color)
        canvas.put(x + w - 1, y + h - 1, br, color)

        for i in range(1, w - 1):
            canvas.put(x + i, y, h_char, color)
            canvas.put(x + i, y + h - 1, h_char, color)

        for i in range(1, h - 1):
            canvas.put(x, y + i, v_char, color)
            canvas.put(x + w - 1, y + i, v_char, color)

    @staticmethod
    def rounded_rect(canvas: Canvas, x: int, y: int, w: int, h: int, color: Color = Color.WHITE, fill: bool = True):
        """Draw a rectangle with rounded corners using block characters."""
        # Corners
        canvas.put(x, y, Brush.CORNER_UL, color)
        canvas.put(x + w - 1, y, Brush.CORNER_UR, color)
        canvas.put(x, y + h - 1, Brush.CORNER_LL, color)
        canvas.put(x + w - 1, y + h - 1, Brush.CORNER_LR, color)

        # Edges
        for i in range(1, w - 1):
            canvas.put(x + i, y, Brush.FULL, color)
            canvas.put(x + i, y + h - 1, Brush.FULL, color)

        for i in range(1, h - 1):
            canvas.put(x, y + i, Brush.HALF_RIGHT, color)
            canvas.put(x + w - 1, y + i, Brush.HALF_LEFT, color)

        # Fill interior
        if fill and h > 2 and w > 2:
            for dy in range(1, h - 1):
                for dx in range(1, w - 1):
                    canvas.put(x + dx, y + dy, Brush.FULL, color)

    @staticmethod
    def text(canvas: Canvas, x: int, y: int, text: str, color: Color = Color.WHITE):
        """Draw text horizontally."""
        for i, char in enumerate(text):
            canvas.put(x + i, y, char, color)

    @staticmethod
    def text_centered(canvas: Canvas, y: int, text: str, color: Color = Color.WHITE):
        """Draw text centered horizontally on the canvas."""
        x = (canvas.width - len(text)) // 2
        Brush.text(canvas, x, y, text, color)

    @staticmethod
    def progress_bar(canvas: Canvas, x: int, y: int, width: int, percent: float,
                     color: Color = Color.WHITE, bg_color: Color = Color.GRAY,
                     filled_char: str = "#", empty_char: str = "-"):
        """Draw a horizontal progress bar using ASCII characters."""
        filled = int(percent / 100 * width)
        for i in range(width):
            if i < filled:
                canvas.put(x + i, y, filled_char, color)
            else:
                canvas.put(x + i, y, empty_char, bg_color)


# =============================================================================
# Sprites - Pre-built Patterns
# =============================================================================

@dataclass
class Sprite:
    """A pre-built character pattern that can be stamped onto a canvas."""
    pattern: list[str]  # Lines of the sprite
    width: int = field(init=False)
    height: int = field(init=False)

    def __post_init__(self):
        self.height = len(self.pattern)
        self.width = max(len(line) for line in self.pattern) if self.pattern else 0

    def to_canvas(self, color: Color = Color.WHITE) -> Canvas:
        """Convert sprite to a canvas."""
        c = Canvas(self.width, self.height)
        for y, line in enumerate(self.pattern):
            for x, char in enumerate(line):
                c.put(x, y, char, color)
        return c

    def stamp(self, canvas: Canvas, x: int, y: int, color: Color = Color.WHITE, transparent: str = " "):
        """Stamp sprite onto canvas at position."""
        for dy, line in enumerate(self.pattern):
            for dx, char in enumerate(line):
                if char != transparent:
                    canvas.put(x + dx, y + dy, char, color)


# Pre-built sprites
SPRITES = {
    # Weather particles
    "snowflake": Sprite(["*"]),
    "raindrop": Sprite(["|"]),
    "cloud_small": Sprite(["_~_"]),
    "cloud_medium": Sprite([" ~~ ", "~~~~"]),

    # Decorations
    "dot": Sprite(["·"]),
    "star": Sprite(["✦"]),
}


# =============================================================================
# Face Builder - Higher-level Avatar Construction
# =============================================================================

class FaceBuilder:
    """Builds expressive faces using canvas and brushes.

    Uses ASCII-compatible characters for proper monospace alignment.
    Based on legacy avatar.py style.
    """

    # Eye characters (single char)
    EYES = {
        "normal":   "o",
        "dots":     ".",
        "closed":   "-",
        "wide":     "O",
        "sleepy":   "_",
        "looking_l": "o",  # Position shifts left
        "looking_r": "o",  # Position shifts right
        "wink_l":   "-",
        "wink_r":   "o",
    }

    # Eye positions: (left_pad, gap, right_pad) - must sum to 7 for 11-char width
    EYE_POSITIONS = {
        "normal":    (3, 1, 3),
        "dots":      (3, 1, 3),
        "closed":    (3, 1, 3),
        "wide":      (3, 1, 3),
        "sleepy":    (3, 1, 3),
        "looking_l": (2, 1, 4),
        "looking_r": (4, 1, 2),
        "wink_l":    (3, 1, 3),
        "wink_r":    (3, 1, 3),
    }

    # Mouth characters (single char, centered)
    MOUTHS = {
        "neutral":  "~",
        "smile":    "u",
        "open":     "o",
        "flat":     "-",
        "dots":     ".",
        "think":    "~",
        "frown":    "n",
    }

    # Border characters by status
    BORDERS = {
        "idle":      "-",
        "resting":   "-",
        "thinking":  "~",
        "running":   "=",
        "executing": "=",
        "awaiting":  ".",
        "reading":   ".",
        "writing":   "-",
        "reviewing": "~",
        "offline":   ".",
    }

    # Substrate patterns (activity indicators)
    SUBSTRATES = {
        "idle":      " .  .  . ",
        "resting":   " .  .  . ",
        "thinking":  " * . * . ",
        "running":   " * o * o ",
        "executing": " > > > > ",
        "awaiting":  " . . . . ",
        "reading":   " > . . . ",
        "writing":   " # # # # ",
        "reviewing": " * . * . ",
        "offline":   "   . .   ",
    }

    @classmethod
    def build(cls, canvas: Canvas, x: int, y: int, color: Color = Color.WHITE,
              eyes: str = "normal", mouth: str = "neutral", status: str = "idle"):
        """
        Build a 5-line tall face at position.

        Structure (11 chars wide, 5 chars tall):
          Row 0:  +---------+   (top border)
          Row 1:  |   o o   |   (eyes row)
          Row 2:  |    ~    |   (mouth row)
          Row 3:  | . . . . |   (substrate)
          Row 4:  +---------+   (bottom border)
        """
        eye_char = cls.EYES.get(eyes, "o")
        eye_pos = cls.EYE_POSITIONS.get(eyes, (3, 1, 3))
        mouth_char = cls.MOUTHS.get(mouth, "~")
        border = cls.BORDERS.get(status, "-")
        substrate = cls.SUBSTRATES.get(status, " .  .  . ")

        l, g, r = eye_pos  # left pad, gap, right pad

        # Row 0: Top border (11 chars)
        Brush.text(canvas, x, y, f"+{border * 9}+", color)

        # Row 1: Eyes (11 chars)
        eye_line = f"|{' ' * l}{eye_char}{' ' * g}{eye_char}{' ' * r}|"
        Brush.text(canvas, x, y + 1, eye_line, color)

        # Row 2: Mouth (11 chars, centered)
        Brush.text(canvas, x, y + 2, f"|    {mouth_char}    |", color)

        # Row 3: Substrate (11 chars)
        Brush.text(canvas, x, y + 3, f"|{substrate}|", color)

        # Row 4: Bottom border (11 chars)
        Brush.text(canvas, x, y + 4, f"+{border * 9}+", color)


# =============================================================================
# Demo
# =============================================================================

def demo():
    """Demonstrate the canvas and brush system."""
    import time

    # Create a canvas
    c = Canvas(20, 10)

    # Draw various elements
    print("\033[2J\033[H")  # Clear screen
    print("Canvas & Brush System Demo\n")

    # 1. Basic shapes
    print("1. Rounded rectangle:")
    c.clear()
    Brush.rounded_rect(c, 2, 1, 8, 4, Color.BRIGHT_BLUE, fill=False)
    print(c.render())
    print()

    # 2. Face
    print("2. Face with expression:")
    c.clear()
    FaceBuilder.build(c, 3, 2, Color.BRIGHT_GREEN, eyes="wide", mouth="smile")
    print(c.render())
    print()

    # 3. Progress bar
    print("3. Progress bar:")
    c.clear()
    Brush.progress_bar(c, 2, 2, 15, 65, Color.BRIGHT_BLUE, Color.GRAY)
    print(c.render())
    print()

    # 4. Animation demo
    print("4. Animation (press Ctrl+C to stop):")
    statuses = [
        ("idle", "dots", "neutral", Color.GRAY),
        ("thinking", "looking_l", "think", Color.YELLOW),
        ("thinking", "normal", "think", Color.YELLOW),
        ("thinking", "looking_r", "think", Color.YELLOW),
        ("running", "wide", "smile", Color.BRIGHT_GREEN),
        ("awaiting", "closed", "dots", Color.BRIGHT_BLUE),
        ("awaiting", "normal", "dots", Color.BRIGHT_BLUE),
    ]

    try:
        for _ in range(3):
            for name, eyes, mouth, color in statuses:
                c.clear()
                FaceBuilder.build(c, 3, 1, color, eyes=eyes, mouth=mouth)
                Brush.text_centered(c, 7, name, color)

                print("\033[12A", end="")  # Move up
                print(c.render())
                print()
                time.sleep(0.3)
    except KeyboardInterrupt:
        pass

    print("\nDone!")


if __name__ == "__main__":
    demo()
