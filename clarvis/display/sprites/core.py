"""Core sprite abstractions: Sprite ABC, SpriteRegistry, BBox."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

SPACE = ord(" ")


@dataclass(frozen=True, slots=True)
class BBox:
    """Bounding box for sprite positioning."""

    x: int
    y: int
    w: int
    h: int

    @property
    def x2(self) -> int:
        return self.x + self.w

    @property
    def y2(self) -> int:
        return self.y + self.h


class Sprite(ABC):
    """Base class for all sprites.

    Sprites are the atomic visual unit. Each has a priority (compositing order),
    a bounding box, and tick/render methods. Sprites can be killed to remove
    them from the scene.
    """

    def __init__(self, priority: int = 0, transparent: bool = True):
        self.priority = priority
        self.transparent = transparent
        self._alive = True

    @property
    def alive(self) -> bool:
        return self._alive

    def kill(self) -> None:
        self._alive = False

    @property
    @abstractmethod
    def bbox(self) -> BBox: ...

    @abstractmethod
    def tick(self, **ctx) -> None: ...

    @abstractmethod
    def render(self, out_chars: np.ndarray, out_colors: np.ndarray) -> None: ...


class SpriteRegistry:
    """Container for sprites with priority-sorted access and lifecycle management."""

    def __init__(self):
        self._sprites: list[Sprite] = []

    def add(self, sprite: Sprite) -> None:
        self._sprites.append(sprite)

    def alive(self) -> list[Sprite]:
        """Return living sprites sorted by priority (low → high)."""
        return sorted(
            (s for s in self._sprites if s.alive),
            key=lambda s: s.priority,
        )

    def by_type[T: Sprite](self, cls: type[T]) -> list[T]:
        """Return living sprites of exact type cls."""
        return [s for s in self._sprites if type(s) is cls and s.alive]

    def process_kills(self) -> None:
        """Remove dead sprites from internal storage."""
        self._sprites = [s for s in self._sprites if s.alive]
