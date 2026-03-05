"""Cel sprite: frame-based animation with named sequences."""

import numpy as np

from .behaviors import Behavior, StaticBehavior
from .core import SPACE, BBox, Sprite


def _parse_frame(frame, width: int, height: int) -> np.ndarray:
    """Convert a frame to a (h, w) uint32 array.

    Accepts either a text string (split on newlines, padded with SPACE)
    or a numpy array (used directly after shape validation).
    """
    if isinstance(frame, np.ndarray):
        if frame.shape != (height, width):
            raise ValueError(f"Frame shape {frame.shape} does not match ({height}, {width})")
        return frame.astype(np.uint32)

    lines = frame.split("\n")
    result = np.full((height, width), SPACE, dtype=np.uint32)
    for row_idx, line in enumerate(lines[:height]):
        for col_idx, ch in enumerate(line[:width]):
            result[row_idx, col_idx] = ord(ch)
    return result


class Cel(Sprite):
    """Frame animation sprite. Workhorse for anything that 'looks like something.'

    Accepts frames as text strings (parsed to uint32 matrices) or
    precomputed numpy arrays directly. Named animation sequences
    select which frame list is active.
    """

    def __init__(
        self,
        animations: dict[str, list],
        default_animation: str,
        x: int,
        y: int,
        width: int,
        height: int,
        priority: int = 0,
        behavior: Behavior | None = None,
        color: int = 0,
        transparent: bool = True,
        **kwargs,
    ):
        super().__init__(priority=priority, transparent=transparent)
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.color = color
        self.behavior = behavior or StaticBehavior()

        # Parse all animation frames upfront
        self._animations: dict[str, list[np.ndarray]] = {}
        for name, frames in animations.items():
            self._animations[name] = [_parse_frame(f, width, height) for f in frames]

        self._current_animation = default_animation
        self._frame_index = 0

    @property
    def bbox(self) -> BBox:
        return BBox(self.x, self.y, self.width, self.height)

    @property
    def current_frames(self) -> list[np.ndarray]:
        return self._animations[self._current_animation]

    @property
    def frame_index(self) -> int:
        return self._frame_index

    def set_animation(self, name: str) -> None:
        """Switch active animation sequence and reset frame index."""
        if name not in self._animations:
            raise KeyError(f"Unknown animation: {name!r}")
        self._current_animation = name
        self._frame_index = 0

    def tick(self, **ctx) -> None:
        """Advance frame counter and run behavior."""
        frames = self.current_frames
        self._frame_index = (self._frame_index + 1) % len(frames)
        self.behavior.update(self, ctx)

    def render(self, out_chars: np.ndarray, out_colors: np.ndarray) -> None:
        """Blit current frame into output arrays at (x, y)."""
        frame = self.current_frames[self._frame_index]
        b = self.bbox
        out_chars[b.y : b.y2, b.x : b.x2] = frame
        # Apply color to non-SPACE cells
        color_region = np.where(frame != SPACE, self.color, 0).astype(np.uint8)
        out_colors[b.y : b.y2, b.x : b.x2] = color_region
