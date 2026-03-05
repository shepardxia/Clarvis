"""Control sprite: click region with stateful label and action dispatch."""

import numpy as np

from .core import SPACE, BBox, Sprite


class Control(Sprite):
    """Click region with stateful label and action dispatch."""

    def __init__(
        self,
        x: int,
        y: int,
        priority: int,
        labels: dict[str, str],
        action_id: str,
        state: str = "enabled",
        visible: bool = True,
        color: int = 0,
        transparent: bool = True,
        **kwargs,
    ):
        super().__init__(priority=priority, transparent=transparent)
        self.x = x
        self.y = y
        self.color = color
        self.labels = labels
        self.action_id = action_id
        self._state = state
        self._visible = visible
        # Width derived from longest label
        self._width = max(len(v) for v in labels.values())

    @property
    def bbox(self) -> BBox:
        return BBox(self.x, self.y, self._width, 1)

    def click_region(self) -> tuple[int, int, int, int]:
        """Return (row, col, width, height) for ClickRegionManager."""
        return (self.y, self.x, self._width, 1)

    def set_state(self, state: str) -> None:
        """Switch to a different label state."""
        if state not in self.labels:
            raise KeyError(f"Unknown state: {state!r}")
        self._state = state

    def set_visible(self, visible: bool) -> None:
        self._visible = visible

    def tick(self, **ctx) -> None:
        pass  # Controls don't animate

    def render(self, out_chars: np.ndarray, out_colors: np.ndarray) -> None:
        """Write current label text to output at position."""
        if not self._visible:
            return
        label = self.labels[self._state]
        b = self.bbox
        for col_idx, ch in enumerate(label[: self._width]):
            out_chars[b.y, b.x + col_idx] = ord(ch)
        # Pad remaining width with SPACE (transparent won't overwrite)
        for col_idx in range(len(label), self._width):
            out_chars[b.y, b.x + col_idx] = SPACE
        # Apply color to non-SPACE cells
        for col_idx in range(self._width):
            if out_chars[b.y, b.x + col_idx] != SPACE:
                out_colors[b.y, b.x + col_idx] = self.color
