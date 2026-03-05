"""Reel sprite: text content with viewport and temporal effects.

Modes: STATIC (fixed text), REVEAL (typewriter), SCROLL (vertical),
MARQUEE (horizontal loop). Same engine handles lyrics, ticker, quotes,
voice text, clock — mode and data source change, rendering doesn't.
"""

from enum import Enum

import numpy as np

from .core import SPACE, BBox, Sprite


class ReelMode(Enum):
    STATIC = "static"
    REVEAL = "reveal"
    SCROLL = "scroll"
    MARQUEE = "marquee"


def _word_wrap(text: str, width: int) -> list[str]:
    """Break text into lines fitting within *width*.

    Splits on newlines first, then wraps each paragraph at spaces.
    Hard-breaks words longer than *width*.
    """
    if width <= 0:
        return []
    paragraphs = text.split("\n")
    lines: list[str] = []
    for para in paragraphs:
        if not para:
            lines.append("")
            continue
        words = para.split(" ")
        current = ""
        for word in words:
            if not word:
                # consecutive spaces — treat as empty token
                if current:
                    current += " "
                continue
            # Hard-break words longer than width
            while len(word) > width:
                chunk = word[:width]
                if current:
                    # flush current line first
                    lines.append(current)
                    current = ""
                lines.append(chunk)
                word = word[width:]
            if not word:
                continue
            if not current:
                current = word
            elif len(current) + 1 + len(word) <= width:
                current += " " + word
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


class Reel(Sprite):
    """Text content with viewport and temporal effects."""

    def __init__(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        priority: int,
        mode: ReelMode = ReelMode.STATIC,
        content: str = "",
        reveal_speed: int = 1,
        scroll_speed: int = 1,
        color: int = 255,
        transparent: bool = True,
        **kwargs,
    ):
        super().__init__(priority=priority, transparent=transparent)
        self._x = x
        self._y = y
        self._width = width
        self._height = height
        self.mode = mode
        self.color = color
        self.reveal_speed = reveal_speed
        self.scroll_speed = scroll_speed

        # Internal state
        self._reveal_pos = 0  # chars revealed (REVEAL mode)
        self._scroll_offset = 0  # line offset (SCROLL mode)
        self._marquee_offset = 0  # char offset (MARQUEE mode)
        self._lines: list[str] = []

        self.set_content(content)

    @property
    def bbox(self) -> BBox:
        return BBox(self._x, self._y, self._width, self._height)

    # -- Content management --

    def set_content(self, text: str) -> None:
        """Update text buffer and reset position state."""
        self._lines = _word_wrap(text, self._width)
        self._reveal_pos = 0
        self._scroll_offset = 0
        self._marquee_offset = 0

    def set_reveal_position(self, chars: int) -> None:
        """Externally set the reveal cursor position."""
        self._reveal_pos = max(0, chars)

    # -- Tick --

    def tick(self, **ctx) -> None:
        if self.mode is ReelMode.REVEAL:
            total = sum(len(line) for line in self._lines)
            if self._reveal_pos < total:
                self._reveal_pos += self.reveal_speed
        elif self.mode is ReelMode.SCROLL:
            max_offset = max(0, len(self._lines) - self._height)
            if self._scroll_offset < max_offset:
                self._scroll_offset += self.scroll_speed
                self._scroll_offset = min(self._scroll_offset, max_offset)
        elif self.mode is ReelMode.MARQUEE:
            self._marquee_offset += self.scroll_speed

    # -- Render --

    def render(self, out_chars: np.ndarray, out_colors: np.ndarray) -> None:
        if not self._lines:
            return

        b = self.bbox

        if self.mode is ReelMode.STATIC:
            self._render_static(out_chars, out_colors, b)
        elif self.mode is ReelMode.REVEAL:
            self._render_reveal(out_chars, out_colors, b)
        elif self.mode is ReelMode.SCROLL:
            self._render_scroll(out_chars, out_colors, b)
        elif self.mode is ReelMode.MARQUEE:
            self._render_marquee(out_chars, out_colors, b)

    def _put_line(
        self,
        out_chars: np.ndarray,
        out_colors: np.ndarray,
        row: int,
        col: int,
        text: str,
        max_chars: int | None = None,
    ) -> None:
        """Write *text* into arrays at (row, col), respecting bounds."""
        if row < 0 or row >= out_chars.shape[0]:
            return
        for i, ch in enumerate(text):
            if max_chars is not None and i >= max_chars:
                break
            cx = col + i
            if cx < 0 or cx >= out_chars.shape[1]:
                continue
            code = ord(ch)
            out_chars[row, cx] = code
            if code != SPACE:
                out_colors[row, cx] = self.color

    def _render_static(self, out_chars, out_colors, b: BBox) -> None:
        for row_i, line in enumerate(self._lines[: self._height]):
            self._put_line(out_chars, out_colors, b.y + row_i, b.x, line)

    def _render_reveal(self, out_chars, out_colors, b: BBox) -> None:
        chars_left = self._reveal_pos
        for row_i, line in enumerate(self._lines[: self._height]):
            if chars_left <= 0:
                break
            visible = min(len(line), chars_left)
            self._put_line(out_chars, out_colors, b.y + row_i, b.x, line, max_chars=visible)
            chars_left -= len(line)

    def _render_scroll(self, out_chars, out_colors, b: BBox) -> None:
        start = self._scroll_offset
        visible = self._lines[start : start + self._height]
        for row_i, line in enumerate(visible):
            self._put_line(out_chars, out_colors, b.y + row_i, b.x, line)

    def _render_marquee(self, out_chars, out_colors, b: BBox) -> None:
        # Marquee: single logical line that scrolls horizontally and wraps
        flat = " ".join(self._lines) if self._lines else ""
        if not flat:
            return
        # Add gap for visual separation when wrapping
        gap = "   "
        looped = flat + gap
        loop_len = len(looped)
        offset = self._marquee_offset % loop_len

        # Build the visible strip
        visible = ""
        for i in range(self._width):
            idx = (offset + i) % loop_len
            visible += looped[idx]

        self._put_line(out_chars, out_colors, b.y, b.x, visible)
