"""SceneManager: canvas controller with compositing and tick loop."""

import numpy as np

from .core import SPACE, Sprite, SpriteRegistry


class SceneManager:
    """Manages a collection of sprites, composites them into a grid.

    Compositing: fills SPACE, iterates alive sprites low→high priority.
    Transparent sprites only overwrite non-SPACE cells.
    PostFx sprites run in a second pass after normal compositing.
    """

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.registry = SpriteRegistry()
        self._out_chars = np.full((height, width), SPACE, dtype=np.uint32)
        self._out_colors = np.zeros((height, width), dtype=np.uint8)
        # Pre-allocated scratch buffers for transparent sprite compositing
        self._scratch_chars = np.full((height, width), SPACE, dtype=np.uint32)
        self._scratch_colors = np.zeros((height, width), dtype=np.uint8)

    def add(self, sprite: Sprite) -> None:
        self.registry.add(sprite)

    def tick(self, **ctx) -> None:
        """Advance all living sprites, then prune dead ones."""
        for sprite in self.registry.alive():
            sprite.tick(**ctx)
        self.registry.process_kills()

    def render(self) -> tuple[np.ndarray, np.ndarray]:
        """Composite all sprites into output arrays."""
        out_c = self._out_chars
        out_k = self._out_colors
        out_c.fill(SPACE)
        out_k.fill(0)

        for sprite in self.registry.alive():
            # Skip PostFx sprites in normal pass
            if hasattr(sprite, "render_post") and callable(sprite.render_post):
                continue

            if sprite.transparent:
                # Render into pre-allocated scratch, then merge non-SPACE
                b = sprite.bbox
                scratch_c = self._scratch_chars
                scratch_k = self._scratch_colors
                # Only clear the bbox region, not the full canvas
                scratch_c[b.y : b.y2, b.x : b.x2].fill(SPACE)
                scratch_k[b.y : b.y2, b.x : b.x2].fill(0)
                sprite.render(scratch_c, scratch_k)
                region = scratch_c[b.y : b.y2, b.x : b.x2]
                mask = region != SPACE
                out_c[b.y : b.y2, b.x : b.x2] = np.where(mask, region, out_c[b.y : b.y2, b.x : b.x2])
                out_k[b.y : b.y2, b.x : b.x2] = np.where(
                    mask,
                    scratch_k[b.y : b.y2, b.x : b.x2],
                    out_k[b.y : b.y2, b.x : b.x2],
                )
            else:
                sprite.render(out_c, out_k)

        # PostFx pass
        for sprite in self.registry.alive():
            if hasattr(sprite, "render_post") and callable(sprite.render_post):
                sprite.render_post(out_c, out_k)

        return out_c, out_k

    def to_grid(self) -> tuple[list[str], list[list[int]]]:
        """Render and return structured grid data.

        Returns:
            (rows, cell_colors) where rows is a list of strings (one per row)
            and cell_colors is a 2D list of ANSI 256 color codes per cell.
        """
        self.render()
        rows = [row.tobytes().decode("utf-32-le") for row in self._out_chars]
        return rows, self._out_colors.tolist()

    # -- Agent API stubs (Phase 2+) --

    def spawn(self, *args, **kwargs):
        raise NotImplementedError

    def remove(self, *args, **kwargs):
        raise NotImplementedError

    def list_sprites(self):
        raise NotImplementedError

    def snapshot(self):
        raise NotImplementedError
