"""Tests for sprites/core.py — Sprite ABC, SpriteRegistry, BBox."""

from clarvis.display.sprites.core import SPACE, BBox, Sprite, SpriteRegistry

# -- Concrete Sprite for testing --


class StubSprite(Sprite):
    """Minimal concrete sprite for testing."""

    def __init__(self, x, y, w, h, priority=0, transparent=True):
        super().__init__(priority=priority, transparent=transparent)
        self._bbox = BBox(x, y, w, h)
        self.tick_count = 0

    @property
    def bbox(self) -> BBox:
        return self._bbox

    def tick(self, **ctx):
        self.tick_count += 1

    def render(self, out_chars, out_colors):
        b = self._bbox
        out_chars[b.y : b.y2, b.x : b.x2] = ord("X")
        out_colors[b.y : b.y2, b.x : b.x2] = 1


# -- BBox --


class TestBBox:
    def test_x2_y2(self):
        b = BBox(2, 3, 5, 4)
        assert b.x2 == 7
        assert b.y2 == 7

    def test_zero_size(self):
        b = BBox(0, 0, 0, 0)
        assert b.x2 == 0
        assert b.y2 == 0


# -- Sprite --


class TestSprite:
    def test_alive_by_default(self):
        s = StubSprite(0, 0, 1, 1)
        assert s.alive

    def test_kill(self):
        s = StubSprite(0, 0, 1, 1)
        s.kill()
        assert not s.alive

    def test_priority(self):
        s = StubSprite(0, 0, 1, 1, priority=42)
        assert s.priority == 42

    def test_transparent_default(self):
        s = StubSprite(0, 0, 1, 1)
        assert s.transparent is True

    def test_transparent_false(self):
        s = StubSprite(0, 0, 1, 1, transparent=False)
        assert s.transparent is False


# -- SpriteRegistry --


class TestSpriteRegistry:
    def test_add_and_alive(self):
        reg = SpriteRegistry()
        s1 = StubSprite(0, 0, 1, 1, priority=10)
        s2 = StubSprite(0, 0, 1, 1, priority=5)
        reg.add(s1)
        reg.add(s2)
        alive = reg.alive()
        assert len(alive) == 2
        # Sorted by priority
        assert alive[0].priority == 5
        assert alive[1].priority == 10

    def test_alive_excludes_dead(self):
        reg = SpriteRegistry()
        s1 = StubSprite(0, 0, 1, 1)
        s2 = StubSprite(0, 0, 1, 1)
        reg.add(s1)
        reg.add(s2)
        s1.kill()
        assert len(reg.alive()) == 1
        assert reg.alive()[0] is s2

    def test_process_kills(self):
        reg = SpriteRegistry()
        s1 = StubSprite(0, 0, 1, 1)
        s2 = StubSprite(0, 0, 1, 1)
        reg.add(s1)
        reg.add(s2)
        s1.kill()
        reg.process_kills()
        # Dead sprite removed from internal list
        assert len(reg._sprites) == 1

    def test_by_type(self):
        reg = SpriteRegistry()
        s = StubSprite(0, 0, 1, 1)
        reg.add(s)
        found = reg.by_type(StubSprite)
        assert len(found) == 1
        assert found[0] is s

    def test_by_type_empty(self):
        reg = SpriteRegistry()
        s = StubSprite(0, 0, 1, 1)
        reg.add(s)
        assert reg.by_type(Sprite) == []  # StubSprite is not exactly Sprite


# -- SPACE constant --


def test_space_constant():
    assert SPACE == ord(" ")
