"""Sandbox pattern: state array + step function + char mapping.

Subclasses provide the engine (state representation, step function,
state-to-char mapping). The base handles lifecycle, compositing,
and the configure() API for agent reprogramming.
"""

from abc import abstractmethod

import numpy as np

from .core import SPACE, BBox, Sprite


class Sandbox(Sprite):
    """Programmable computational simulation.

    Subclasses provide the engine: state representation, step function,
    and state-to-char mapping. The base handles lifecycle, compositing,
    and the configure() API for agent reprogramming.
    """

    def __init__(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        priority: int = 0,
        char_map: dict[int, str] | str | None = None,
        lifetime: int | None = None,
        transparent: bool = True,
        **kwargs,
    ):
        super().__init__(priority=priority, transparent=transparent)
        self._bbox = BBox(x, y, width, height)
        self._char_map = char_map
        self._lifetime = lifetime
        self.age = 0

    @property
    def bbox(self) -> BBox:
        return self._bbox

    @abstractmethod
    def step(self) -> None:
        """Advance simulation one tick. Subclasses implement."""
        ...

    def configure(self, **config) -> None:
        """Update engine parameters. Override in subclasses."""
        pass

    def tick(self, **ctx) -> None:
        self.age += 1
        if self._lifetime is not None and self.age > self._lifetime:
            self.kill()
            return
        self.step()

    def _resolve_char(self, value: int) -> int:
        """Map a state value to a character ordinal via char_map."""
        if self._char_map is None:
            return SPACE
        if isinstance(self._char_map, str):
            idx = int(value) % len(self._char_map)
            return ord(self._char_map[idx])
        # dict mapping
        ch = self._char_map.get(int(value))
        if ch is None:
            return SPACE
        return ord(ch)

    @abstractmethod
    def state_array(self) -> np.ndarray:
        """Return the 2D state array (height x width) for rendering."""
        ...

    def render(self, out_chars: np.ndarray, out_colors: np.ndarray) -> None:
        b = self._bbox
        state = self.state_array()
        for row in range(b.h):
            for col in range(b.w):
                ch = self._resolve_char(state[row, col])
                if self.transparent and ch == SPACE:
                    continue
                out_chars[b.y + row, b.x + col] = ch
