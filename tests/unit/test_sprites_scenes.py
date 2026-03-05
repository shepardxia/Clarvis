"""Tests for sprites/scenes.py — SceneManager."""

from clarvis.display.sprites.core import BBox, Sprite
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


class TestSceneManagerEmpty:
    def test_empty_scene_all_spaces(self):
        scene = SceneManager(10, 5)
        rows, colors = scene.to_grid()
        assert len(rows) == 5
        assert all(len(r) == 10 for r in rows)
        assert all(c == " " for row in rows for c in row)

    def test_empty_scene_colors_zero(self):
        scene = SceneManager(10, 5)
        _, colors = scene.to_grid()
        assert all(c == 0 for row in colors for c in row)


class TestSceneManagerCompositing:
    def test_opaque_sprite_writes_bbox(self):
        scene = SceneManager(5, 3)
        scene.add(FillSprite(1, 0, 2, 2, char="A", transparent=False))
        rows, _ = scene.to_grid()
        assert rows[0][1] == "A"
        assert rows[0][2] == "A"
        assert rows[1][1] == "A"
        # Outside bbox = space
        assert rows[0][0] == " "

    def test_higher_priority_overwrites(self):
        scene = SceneManager(5, 3)
        scene.add(FillSprite(0, 0, 3, 1, char="L", priority=0, transparent=False))
        scene.add(FillSprite(1, 0, 1, 1, char="H", priority=10, transparent=False))
        rows, _ = scene.to_grid()
        assert rows[0][0] == "L"
        assert rows[0][1] == "H"  # overwritten by higher priority
        assert rows[0][2] == "L"

    def test_transparent_sprite_preserves_spaces(self):
        scene = SceneManager(5, 3)
        scene.add(FillSprite(0, 0, 5, 1, char="B", priority=0, transparent=False))
        scene.add(TransparentSprite(1, 0, priority=10))
        rows, _ = scene.to_grid()
        # TransparentSprite writes "A B" at (1,0)
        assert rows[0][0] == "B"  # untouched by transparent sprite
        assert rows[0][1] == "A"  # overwritten
        assert rows[0][2] == "B"  # SPACE in transparent sprite, background shows through
        assert rows[0][3] == "B"  # overwritten


class TestSceneManagerTick:
    def test_tick_calls_all_sprites(self):
        scene = SceneManager(5, 3)
        s1 = FillSprite(0, 0, 1, 1)
        s2 = FillSprite(1, 1, 1, 1)
        scene.add(s1)
        scene.add(s2)
        scene.tick(status="idle")
        assert s1.ticked
        assert s2.ticked

    def test_dead_sprites_excluded_after_tick(self):
        scene = SceneManager(5, 3)
        s1 = FillSprite(0, 0, 2, 2, char="A")
        s2 = FillSprite(0, 0, 2, 2, char="B", priority=10)
        scene.add(s1)
        scene.add(s2)
        s2.kill()
        scene.tick()
        rows, _ = scene.to_grid()
        # s2 is dead, so s1's "A" should show
        assert rows[0][0] == "A"


class TestSceneManagerScratchArrays:
    def test_scratch_arrays_exist_with_correct_shape(self):
        scene = SceneManager(10, 5)
        assert scene._scratch_chars.shape == (5, 10)
        assert scene._scratch_colors.shape == (5, 10)

    def test_scratch_arrays_reused_across_renders(self):
        scene = SceneManager(5, 3)
        scene.add(TransparentSprite(0, 0, priority=10))
        scene.render()
        id_c = id(scene._scratch_chars)
        id_k = id(scene._scratch_colors)
        scene.render()
        assert id(scene._scratch_chars) == id_c
        assert id(scene._scratch_colors) == id_k


class TestSceneManagerToGrid:
    def test_to_grid_shape(self):
        scene = SceneManager(8, 4)
        rows, colors = scene.to_grid()
        assert len(rows) == 4
        assert all(len(r) == 8 for r in rows)
        assert len(colors) == 4
        assert all(len(c) == 8 for c in colors)
