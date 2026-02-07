"""
Progress archetype - renders progress bars using matrix blit.
"""

import numpy as np

from ..elements.registry import ElementRegistry
from ..widget.pipeline import Layer
from .base import Archetype

# Character codes
FILLED = ord("#")
EMPTY = ord("-")


class ProgressArchetype(Archetype):
    """
    Renders a progress bar as a 1-row matrix.

    Uses percentage-based caching for instant rendering of integer percentages.
    """

    def __init__(self, registry: ElementRegistry, width: int = 11):
        self.bar_width = width
        super().__init__(registry, "progress")

        # Pre-allocate bar matrices (chars and colors)
        self._chars = np.full((1, width), EMPTY, dtype=np.uint32)
        self._colors = np.full((1, width), 8, dtype=np.uint8)  # Default gray

        # Percentage cache: int(percent) -> (chars_matrix, colors_matrix)
        self._percent_cache: dict[int, tuple[np.ndarray, np.ndarray]] = {}

    def _on_element_change(self, kind: str, name: str) -> None:
        """No relevant elements to watch."""
        pass

    def prewarm_cache(self) -> dict[str, int]:
        """Pre-compute matrices for all integer percentages (0-100).

        Returns stats dict with cache info.
        """
        for pct in range(101):
            self._cache_percent(pct)
        return {
            "cached_percentages": len(self._percent_cache),
            "memory_bytes": sum(c.nbytes + col.nbytes for c, col in self._percent_cache.values()),
        }

    def _cache_percent(self, percent: int) -> tuple[np.ndarray, np.ndarray]:
        """Compute and cache matrix for given integer percentage."""
        if percent in self._percent_cache:
            return self._percent_cache[percent]

        filled = int(percent / 100 * self.bar_width)

        chars = np.full((1, self.bar_width), EMPTY, dtype=np.uint32)
        chars[0, :filled] = FILLED

        # Colors array (will be overwritten at render time with actual color)
        colors = np.full((1, self.bar_width), 8, dtype=np.uint8)
        colors[0, :filled] = 15  # Bright white for filled

        self._percent_cache[percent] = (chars, colors)
        return chars, colors

    def cache_stats(self) -> dict:
        """Return cache statistics."""
        total_bytes = sum(c.nbytes + col.nbytes for c, col in self._percent_cache.values())
        return {
            "cached_percentages": len(self._percent_cache),
            "memory_bytes": total_bytes,
            "memory_kb": total_bytes / 1024,
        }

    def render(self, layer: Layer, x: int = 0, y: int = 0, percent: float = 0.0, color: int = 8, **kwargs) -> None:
        """
        Render progress bar to layer using cached matrices when possible.

        Args:
            layer: Target layer
            x, y: Position
            percent: Fill percentage (0-100)
            color: Color for empty portion
        """
        percent = max(0.0, min(100.0, float(percent)))
        int_percent = int(percent)

        # Use cached matrix for integer percentages
        if int_percent == percent or abs(percent - int_percent) < 0.5:
            chars, colors = self._cache_percent(int_percent)
            # Update empty portion color
            filled = int(int_percent / 100 * self.bar_width)
            colors_copy = colors.copy()
            colors_copy[0, filled:] = color
            layer.blit(x, y, chars, colors_copy)
        else:
            # Fractional percentage - compute on the fly
            filled = int(percent / 100 * self.bar_width)
            self._chars[:] = EMPTY
            self._chars[0, :filled] = FILLED
            self._colors[:] = color
            self._colors[0, :filled] = 15
            layer.blit(x, y, self._chars, self._colors)
