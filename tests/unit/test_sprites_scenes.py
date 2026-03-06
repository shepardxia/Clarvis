"""Tests for sprites/scenes.py — SceneManager and SpriteRegistry."""

from clarvis.display.sprites.core import BBox, Sprite, SpriteRegistry
from clarvis.display.sprites.scenes import SceneManager


class FillSprite(Sprite):
    """Fills its bbox with a given char."""

    def __init__(self, x, y, w, h, char="X", priority=0, transparent=True):
        super().__init__(priority=priority, transparent=transparent)
        self._bbox = BBox(x, y, w, h)
        self._char = ord(char)
        self.ticked = False

    @property
    def bbox(self):
        return self._bbox

    def tick(self, **ctx):
        self.ticked = True

    def render(self, out_chars, out_colors):
        b = self._bbox
        out_chars[b.y : b.y2, b.x : b.x2] = self._char
        out_colors[b.y : b.y2, b.x : b.x2] = 1


class TransparentSprite(Sprite):
    """Writes char only to some cells, leaves others as SPACE."""

    def __init__(self, x, y, priority=50):
        super().__init__(priority=priority, transparent=True)
        self._bbox = BBox(x, y, 3, 1)

    @property
    def bbox(self):
        return self._bbox

    def tick(self, **ctx):
        pass

    def render(self, out_chars, out_colors):
        b = self._bbox
        # Write "A B" — middle cell stays SPACE
        out_chars[b.y, b.x] = ord("A")
        out_chars[b.y, b.x + 2] = ord("B")
        out_colors[b.y, b.x] = 2
        out_colors[b.y, b.x + 2] = 2


def test_registry_lifecycle():
    """Registry: add sprites -> priority order -> kill -> exclude from alive -> process removes dead."""
    reg = SpriteRegistry()

    # Add sprites with different priorities
    s1 = FillSprite(0, 0, 1, 1, priority=10)
    s2 = FillSprite(0, 0, 1, 1, priority=5)
    s3 = FillSprite(0, 0, 1, 1, priority=7)
    reg.add(s1)
    reg.add(s2)
    reg.add(s3)

    # Verify priority-sorted order
    alive = reg.alive()
    assert len(alive) == 3
    assert alive[0].priority == 5
    assert alive[1].priority == 7
    assert alive[2].priority == 10

    # Kill one sprite — excluded from alive but still in internal storage
    s2.kill()
    alive = reg.alive()
    assert len(alive) == 2
    assert all(s is not s2 for s in alive)

    # Process kills — dead sprite removed from internal list
    reg.process_kills()
    assert len(reg._sprites) == 2


def test_compositing_pipeline():
    """Full compositing pipeline: empty canvas -> opaque -> priority overwrite ->
    transparent preservation -> dead sprite exclusion."""

    # Phase 1: empty scene is all spaces
    scene = SceneManager(10, 5)
    rows, colors = scene.to_grid()
    assert len(rows) == 5
    assert all(len(r) == 10 for r in rows)
    assert all(c == " " for row in rows for c in row)

    # Phase 2: opaque sprite writes into its bbox
    scene = SceneManager(5, 3)
    scene.add(FillSprite(1, 0, 2, 2, char="A", transparent=False))
    rows, _ = scene.to_grid()
    assert rows[0][1] == "A"
    assert rows[0][2] == "A"
    assert rows[1][1] == "A"
    assert rows[0][0] == " "  # outside bbox

    # Phase 3: higher priority overwrites lower
    scene = SceneManager(5, 3)
    scene.add(FillSprite(0, 0, 3, 1, char="L", priority=0, transparent=False))
    scene.add(FillSprite(1, 0, 1, 1, char="H", priority=10, transparent=False))
    rows, _ = scene.to_grid()
    assert rows[0][0] == "L"
    assert rows[0][1] == "H"  # overwritten by higher priority
    assert rows[0][2] == "L"

    # Phase 4: transparent sprite preserves SPACE cells (background shows through)
    scene = SceneManager(5, 3)
    scene.add(FillSprite(0, 0, 5, 1, char="B", priority=0, transparent=False))
    scene.add(TransparentSprite(1, 0, priority=10))
    rows, _ = scene.to_grid()
    assert rows[0][0] == "B"  # untouched by transparent sprite
    assert rows[0][1] == "A"  # overwritten
    assert rows[0][2] == "B"  # SPACE in transparent sprite, background shows through
    assert rows[0][3] == "B"  # overwritten

    # Phase 5: dead sprites excluded after tick
    scene = SceneManager(5, 3)
    s1 = FillSprite(0, 0, 2, 2, char="A")
    s2 = FillSprite(0, 0, 2, 2, char="B", priority=10)
    scene.add(s1)
    scene.add(s2)
    s2.kill()
    scene.tick()
    rows, _ = scene.to_grid()
    assert rows[0][0] == "A"  # s2 is dead, s1's "A" shows
