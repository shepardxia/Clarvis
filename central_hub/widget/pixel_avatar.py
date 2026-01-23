#!/usr/bin/env python3
"""
Pixel art avatar renderer using Unicode block characters.

Block character reference:
  █ - Full block       ░ - Light shade
  ▀ - Upper half       ▄ - Lower half
  ▌ - Left half        ▐ - Right half
  ▛ - Upper-left       ▜ - Upper-right
  ▙ - Lower-left       ▟ - Lower-right
  ▝ - Lower-right quad ▘ - Upper-left quad
  ▗ - Lower-left quad  ▖ - Upper-right quad
"""

from dataclasses import dataclass
from enum import Enum


class Color(Enum):
    """ANSI color codes."""
    RESET = "\033[0m"
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    GRAY = "\033[90m"

    # Bright versions
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_CYAN = "\033[96m"


# Status to color mapping
STATUS_COLORS = {
    "idle": Color.GRAY,
    "resting": Color.GRAY,
    "thinking": Color.YELLOW,
    "running": Color.BRIGHT_GREEN,
    "executing": Color.BRIGHT_GREEN,
    "awaiting": Color.BRIGHT_BLUE,
    "reading": Color.CYAN,
    "writing": Color.BRIGHT_CYAN,
    "reviewing": Color.MAGENTA,
    "offline": Color.GRAY,
}


@dataclass
class PixelFrame:
    """A single animation frame."""
    lines: list[str]

    def render(self, color: Color = Color.WHITE) -> str:
        """Render frame with color."""
        colored_lines = [f"{color.value}{line}{Color.RESET.value}" for line in self.lines]
        return "\n".join(colored_lines)

    def __str__(self) -> str:
        return "\n".join(self.lines)


# Base avatar shape (neutral face)
AVATAR_BASE = PixelFrame(lines=[
    "   ▐▛███▜▌   ",
    "  ▝▜█████▛▘  ",
    "    ▘▘ ▝▝    ",
])

# Eye variations for different states
EYES = {
    "open":    "█   █",    # Standard open eyes
    "closed":  "▀   ▀",    # Closed/blinking
    "looking": "▐█ █▌",    # Looking to side
    "wide":    "██ ██",    # Surprised/alert
    "sleepy":  "▄   ▄",    # Half-closed
    "dots":    "·   ·",    # Minimal
}

# Mouth variations
MOUTHS = {
    "neutral": " ▀▀▀ ",
    "smile":   " ╰─╯ ",
    "open":    "  ○  ",
    "flat":    " ─── ",
    "dots":    " · · ",
    "thinking": " ~~~ ",
}


def build_avatar(status: str, frame_index: int = 0) -> PixelFrame:
    """Build avatar frame based on status and animation frame."""

    # Select eye and mouth based on status
    if status == "idle":
        eye = EYES["dots"] if frame_index % 4 == 0 else EYES["open"]
        mouth = MOUTHS["neutral"]
    elif status == "resting":
        eye = EYES["sleepy"]
        mouth = MOUTHS["neutral"]
    elif status == "thinking":
        # Animate eyes looking around
        eye_options = [EYES["open"], EYES["looking"], EYES["open"], " █ █ "]
        eye = eye_options[frame_index % len(eye_options)]
        mouth = MOUTHS["thinking"]
    elif status in ("running", "executing"):
        eye = EYES["wide"]
        mouth = MOUTHS["smile"]
    elif status == "awaiting":
        # Blink animation
        eye = EYES["closed"] if frame_index % 3 == 0 else EYES["open"]
        mouth = MOUTHS["dots"]
    elif status == "reading":
        eye_options = [EYES["open"], EYES["looking"], "█▌ ▐█", EYES["looking"]]
        eye = eye_options[frame_index % len(eye_options)]
        mouth = MOUTHS["open"]
    elif status == "writing":
        eye = EYES["open"]
        mouth = MOUTHS["flat"]
    elif status == "reviewing":
        eye = EYES["looking"]
        mouth = MOUTHS["thinking"]
    else:  # offline or unknown
        eye = EYES["closed"]
        mouth = MOUTHS["flat"]

    # Build the frame
    # Row 1: Top of head
    row1 = "   ▐▛███▜▌   "

    # Row 2: Eyes row (inside head)
    # Format: edge + eye content + edge
    row2 = f"  ▐ {eye} ▌  "

    # Row 3: Mouth row
    row3 = f"  ▐{mouth}▌  "

    # Row 4: Bottom of head
    row4 = "  ▝▜█████▛▘  "

    # Row 5: Body/substrate hint
    row5 = "    ▘▘ ▝▝    "

    return PixelFrame(lines=[row1, row2, row3, row4, row5])


def get_status_color(status: str) -> Color:
    """Get the color for a given status."""
    return STATUS_COLORS.get(status, Color.WHITE)


def render_avatar(status: str, frame_index: int = 0) -> str:
    """Render a complete colored avatar frame."""
    frame = build_avatar(status, frame_index)
    color = get_status_color(status)
    return frame.render(color)


def animate_demo():
    """Demo animation in terminal."""
    import time
    import sys

    statuses = ["idle", "thinking", "running", "awaiting", "reading", "writing"]

    print("\033[2J\033[H", end="")  # Clear screen
    print("Clarvis Pixel Avatar Demo")
    print("=" * 30)
    print()

    for status in statuses:
        print(f"\nStatus: {status}")
        print("-" * 20)

        for frame in range(8):
            # Move cursor up to redraw
            print(f"\033[6A", end="")  # Move up 6 lines

            # Print the avatar
            output = render_avatar(status, frame)
            print(output)
            print()

            time.sleep(0.3)

        time.sleep(0.5)

    print("\nDone!")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        # Show specific status
        status = sys.argv[1]
        print(f"\nStatus: {status}")
        print(render_avatar(status, 0))
    else:
        # Run demo
        animate_demo()
