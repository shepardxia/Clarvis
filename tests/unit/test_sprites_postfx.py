"""Tests for sprites/postfx.py -- PostFx post-processing effects."""

import numpy as np

from clarvis.display.sprites.core import BBox, Sprite
from clarvis.display.sprites.postfx import PostFx
from clarvis.display.sprites.scenes import SceneManager


class InvertFx(PostFx):
    """Test PostFx that replaces all 'A' chars with 'Z'."""

    def _apply(self, out_chars, out_colors):
        mask = out_chars == ord("A")
        out_chars[mask] = ord("Z")


class ColorShiftFx(PostFx):
    """Test PostFx that adds 10 to all non-zero color values."""

    def _apply(self, out_chars, out_colors):
        mask = out_colors != 0
        out_colors[mask] += 10


class FillSprite(Sprite):
    """Fills its bbox with a given char."""

    def __init__(self, x, y, w, h, char="X", color=1, priority=0, transparent=True):
        super().__init__(priority=priority, transparent=transparent)
        self._bbox = BBox(x, y, w, h)
        self._char = ord(char)
        self._color = color

    @property
    def bbox(self):
        return self._bbox

    def tick(self, **ctx):
        pass

    def render(self, out_chars, out_colors):
        b = self._bbox
        out_chars[b.y : b.y2, b.x : b.x2] = self._char
        out_colors[b.y : b.y2, b.x : b.x2] = self._color


def test_postfx_apply_and_disable():
    """render() is a no-op, render_post() applies the effect, disabled skips."""

    # Phase 1: render() does not modify arrays (contract)
    fx = InvertFx()
    chars = np.full((3, 5), ord("A"), dtype=np.uint32)
    colors = np.ones((3, 5), dtype=np.uint8)
    chars_copy = chars.copy()
    colors_copy = colors.copy()
    fx.render(chars, colors)
    np.testing.assert_array_equal(chars, chars_copy)
    np.testing.assert_array_equal(colors, colors_copy)

    # Phase 2: render_post() applies the effect
    fx2 = InvertFx()
    chars = np.full((3, 5), ord("A"), dtype=np.uint32)
    colors = np.zeros((3, 5), dtype=np.uint8)
    fx2.render_post(chars, colors)
    assert np.all(chars == ord("Z"))

    # Phase 3: disabled fx skips apply
    fx3 = InvertFx(enabled=False)
    chars = np.full((2, 3), ord("A"), dtype=np.uint32)
    colors = np.zeros((2, 3), dtype=np.uint8)
    chars_copy = chars.copy()
    fx3.render_post(chars, colors)
    np.testing.assert_array_equal(chars, chars_copy)


def test_postfx_scene_compositing():
    """Full PostFx scene pipeline: modifies composited output, no-op in normal pass,
    chains in priority order, disabled skipped, dead excluded."""

    # Phase 1: PostFx modifies composited output from normal sprites
    scene = SceneManager(5, 3)
    scene.add(FillSprite(0, 0, 5, 3, char="A", transparent=False))
    scene.add(InvertFx())
    rows, _ = scene.to_grid()
    for row in rows:
        assert all(c == "Z" for c in row)

    # Phase 2: PostFx render() is no-op — doesn't contribute chars in normal pass
    scene = SceneManager(5, 3)
    scene.add(InvertFx())
    rows, _ = scene.to_grid()
    for row in rows:
        assert all(c == " " for c in row)

    # Phase 3: multiple PostFx chain in priority order
    scene = SceneManager(5, 1)
    scene.add(FillSprite(0, 0, 5, 1, char="A", color=1, transparent=False))
    scene.add(InvertFx(priority=50))  # A -> Z
    scene.add(ColorShiftFx(priority=60))  # color 1 -> 11
    rows, colors = scene.to_grid()
    assert all(c == "Z" for c in rows[0])
    assert all(c == 11 for c in colors[0])

    # Phase 4: disabled PostFx does not modify output
    scene = SceneManager(5, 1)
    scene.add(FillSprite(0, 0, 5, 1, char="A", transparent=False))
    scene.add(InvertFx(enabled=False))
    rows, _ = scene.to_grid()
    assert all(c == "A" for c in rows[0])

    # Phase 5: dead PostFx excluded from render pass
    scene = SceneManager(5, 1)
    scene.add(FillSprite(0, 0, 5, 1, char="A", transparent=False))
    fx = InvertFx()
    scene.add(fx)
    fx.kill()
    rows, _ = scene.to_grid()
    assert all(c == "A" for c in rows[0])


def test_postfx_with_transparency():
    """PostFx runs on the composited result including transparent sprites."""
    scene = SceneManager(5, 1)
    # Background: B's
    scene.add(FillSprite(0, 0, 5, 1, char="B", transparent=False, priority=0))
    # Transparent sprite writes A at position 2
    scene.add(FillSprite(2, 0, 1, 1, char="A", transparent=True, priority=10))
    # InvertFx changes A -> Z
    scene.add(InvertFx())
    rows, _ = scene.to_grid()
    assert rows[0][0] == "B"
    assert rows[0][1] == "B"
    assert rows[0][2] == "Z"  # A was changed to Z by PostFx
    assert rows[0][3] == "B"
    assert rows[0][4] == "B"
