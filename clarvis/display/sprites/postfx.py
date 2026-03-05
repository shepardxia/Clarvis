"""PostFx: post-processing effects on composited output."""

from abc import abstractmethod

import numpy as np

from .core import BBox, Sprite


class PostFx(Sprite):
    """Post-processing effect on composited output.

    Unlike normal sprites, PostFx.render_post() runs AFTER compositing
    and receives the final output arrays to modify in-place.
    PostFx.render() is a no-op -- it doesn't participate in normal compositing.
    """

    def __init__(self, priority: int = 100, enabled: bool = True, **kwargs):
        super().__init__(priority=priority, transparent=True)
        self.enabled = enabled

    @property
    def bbox(self) -> BBox:
        return BBox(0, 0, 0, 0)  # PostFx is global, no spatial bbox

    def render(self, out_chars: np.ndarray, out_colors: np.ndarray) -> None:
        pass  # no-op -- PostFx doesn't participate in normal compositing

    def tick(self, **ctx) -> None:
        pass  # Override in subclasses if needed

    def render_post(self, out_chars: np.ndarray, out_colors: np.ndarray) -> None:
        """Apply post-processing if enabled, delegating to _apply."""
        if not self.enabled:
            return
        self._apply(out_chars, out_colors)

    @abstractmethod
    def _apply(self, out_chars: np.ndarray, out_colors: np.ndarray) -> None:
        """Modify the composited output in-place. Subclasses implement this."""
        ...
