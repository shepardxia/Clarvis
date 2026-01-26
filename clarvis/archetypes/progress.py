"""
Progress archetype - renders progress bars using matrix blit.
"""

import numpy as np

from ..widget.pipeline import Layer
from ..elements.registry import ElementRegistry
from .base import Archetype


# Character codes
FILLED = ord('#')
EMPTY = ord('-')


class ProgressArchetype(Archetype):
    """
    Renders a progress bar as a 1-row matrix.
    """

    def __init__(self, registry: ElementRegistry, width: int = 11):
        self.bar_width = width
        super().__init__(registry, 'progress')

        # Pre-allocate bar matrices (chars and colors)
        self._chars = np.full((1, width), EMPTY, dtype=np.uint32)
        self._colors = np.full((1, width), 8, dtype=np.uint8)  # Default gray

    def _on_element_change(self, kind: str, name: str) -> None:
        """No relevant elements to watch."""
        pass

    def render(self, layer: Layer, x: int = 0, y: int = 0,
               percent: float = 0.0, color: int = 8, **kwargs) -> None:
        """
        Render progress bar to layer using matrix blit.

        Args:
            layer: Target layer
            x, y: Position
            percent: Fill percentage (0-100)
            color: Color for empty portion
        """
        percent = max(0.0, min(100.0, float(percent)))
        filled = int(percent / 100 * self.bar_width)

        # Build bar matrix
        self._chars[:] = EMPTY
        self._chars[0, :filled] = FILLED

        self._colors[:] = color
        self._colors[0, :filled] = 15  # Bright white for filled

        # Blit to layer
        layer.blit(x, y, self._chars, self._colors)
