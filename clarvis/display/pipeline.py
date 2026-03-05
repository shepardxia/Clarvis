"""
Layer primitive for rendering into numpy char/color arrays.

Provides blit, put, and put_text operations with bounding box tracking.
Used by archetypes and system sprites as a rendering surface.
"""

from typing import Callable

import numpy as np

# Space character code - background fill
SPACE = ord(" ")


class Layer:
    """A single rendering layer with char and color arrays and bounding box tracking."""

    def __init__(
        self,
        name: str,
        priority: int,
        width: int,
        height: int,
        render_func: Callable[["Layer"], None] | None = None,
        transparent: bool = False,
    ):
        self.name = name
        self.priority = priority
        self.width = width
        self.height = height
        self.render_func = render_func
        self.transparent = transparent

        # NumPy arrays for vectorized operations
        self.chars = np.full((height, width), SPACE, dtype=np.uint32)
        self.colors = np.zeros((height, width), dtype=np.uint8)

        # Bounding box of rendered content (None = empty layer)
        self._bbox: tuple[int, int, int, int] | None = None  # (x1, y1, x2, y2)

    def _expand_bbox(self, x: int, y: int) -> None:
        """Expand bounding box to include point (x, y)."""
        if self._bbox is None:
            self._bbox = (x, y, x + 1, y + 1)
        else:
            x1, y1, x2, y2 = self._bbox
            self._bbox = (min(x1, x), min(y1, y), max(x2, x + 1), max(y2, y + 1))

    def _expand_bbox_rect(self, x: int, y: int, w: int, h: int) -> None:
        """Expand bounding box to include rectangle."""
        if w <= 0 or h <= 0:
            return
        if self._bbox is None:
            self._bbox = (x, y, x + w, y + h)
        else:
            x1, y1, x2, y2 = self._bbox
            self._bbox = (min(x1, x), min(y1, y), max(x2, x + w), max(y2, y + h))

    @property
    def bbox(self) -> tuple[int, int, int, int] | None:
        """Get bounding box (x1, y1, x2, y2) or None if empty."""
        return self._bbox

    def clear(self):
        """Clear layer and reset bounding box."""
        self.chars.fill(SPACE)
        self.colors.fill(0)
        self._bbox = None

    def put(self, x: int, y: int, char: str, color: int = 7):
        """Put a single character at position."""
        if 0 <= x < self.width and 0 <= y < self.height:
            self.chars[y, x] = ord(char)
            self.colors[y, x] = color
            self._expand_bbox(x, y)

    def put_text(self, x: int, y: int, text: str, color: int = 7):
        """Put a string horizontally (convenience method)."""
        if not text or y < 0 or y >= self.height:
            return
        # Convert to 1-row matrix and blit
        x1 = max(0, x)
        x2 = min(self.width, x + len(text))
        if x1 >= x2:
            return
        start = x1 - x
        end = x2 - x
        row = np.array([[ord(c) for c in text[start:end]]], dtype=np.uint32)
        self.blit(x1, y, row, color)

    def blit(self, x: int, y: int, char_matrix: np.ndarray, color: int | np.ndarray = 7):
        """
        Blit a 2D character matrix to the layer at position.

        Args:
            x, y: Top-left position
            char_matrix: 2D numpy array of uint32 char codes (shape: height, width)
            color: Single color int or 2D array matching char_matrix shape
        """
        src_h, src_w = char_matrix.shape

        # Calculate clipped regions
        src_x1 = max(0, -x)
        src_y1 = max(0, -y)
        src_x2 = min(src_w, self.width - x)
        src_y2 = min(src_h, self.height - y)

        dst_x1 = max(0, x)
        dst_y1 = max(0, y)
        dst_x2 = dst_x1 + (src_x2 - src_x1)
        dst_y2 = dst_y1 + (src_y2 - src_y1)

        if dst_x1 >= dst_x2 or dst_y1 >= dst_y2:
            return  # Completely off-screen

        # Blit characters
        self.chars[dst_y1:dst_y2, dst_x1:dst_x2] = char_matrix[src_y1:src_y2, src_x1:src_x2]

        # Blit colors
        if isinstance(color, np.ndarray):
            self.colors[dst_y1:dst_y2, dst_x1:dst_x2] = color[src_y1:src_y2, src_x1:src_x2]
        else:
            self.colors[dst_y1:dst_y2, dst_x1:dst_x2] = color

        # Update bbox
        self._expand_bbox_rect(dst_x1, dst_y1, dst_x2 - dst_x1, dst_y2 - dst_y1)
