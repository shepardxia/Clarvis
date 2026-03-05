"""Tests for sprites/postfx.py -- PostFx post-processing effects."""

import numpy as np

from clarvis.display.sprites.core import SPACE, BBox, Sprite
from clarvis.display.sprites.postfx import PostFx
from clarvis.display.sprites.scenes import SceneManager

# -- Concrete test helpers --


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


# -- PostFx unit tests --


class TestPostFxBase:
    def test_bbox_is_zero(self):
        fx = InvertFx()
        assert fx.bbox == BBox(0, 0, 0, 0)

    def test_render_is_noop(self):
        fx = InvertFx()
        chars = np.full((3, 5), ord("A"), dtype=np.uint32)
        colors = np.ones((3, 5), dtype=np.uint8)
        chars_copy = chars.copy()
        colors_copy = colors.copy()
        fx.render(chars, colors)
        np.testing.assert_array_equal(chars, chars_copy)
        np.testing.assert_array_equal(colors, colors_copy)

    def test_priority_default(self):
        fx = InvertFx()
        assert fx.priority == 100

    def test_priority_custom(self):
        fx = InvertFx(priority=50)
        assert fx.priority == 50

    def test_transparent_always_true(self):
        fx = InvertFx()
        assert fx.transparent is True

    def test_enabled_default_true(self):
        fx = InvertFx()
        assert fx.enabled is True

    def test_tick_is_noop(self):
        fx = InvertFx()
        # Should not raise
        fx.tick(status="idle")


class TestPostFxRenderPost:
    def test_render_post_modifies_chars(self):
        fx = InvertFx()
        chars = np.full((3, 5), ord("A"), dtype=np.uint32)
        colors = np.zeros((3, 5), dtype=np.uint8)
        fx.render_post(chars, colors)
        # All A's should become Z's
        assert np.all(chars == ord("Z"))

    def test_render_post_selective_replacement(self):
        fx = InvertFx()
        chars = np.full((2, 4), SPACE, dtype=np.uint32)
        colors = np.zeros((2, 4), dtype=np.uint8)
        chars[0, 0] = ord("A")
        chars[0, 1] = ord("B")
        chars[1, 0] = ord("A")
        fx.render_post(chars, colors)
        assert chars[0, 0] == ord("Z")
        assert chars[0, 1] == ord("B")  # untouched
        assert chars[1, 0] == ord("Z")

    def test_disabled_fx_skips_apply(self):
        fx = InvertFx(enabled=False)
        chars = np.full((2, 3), ord("A"), dtype=np.uint32)
        colors = np.zeros((2, 3), dtype=np.uint8)
        chars_copy = chars.copy()
        fx.render_post(chars, colors)
        np.testing.assert_array_equal(chars, chars_copy)

    def test_enable_disable_toggle(self):
        fx = InvertFx(enabled=False)
        chars = np.full((1, 3), ord("A"), dtype=np.uint32)
        colors = np.zeros((1, 3), dtype=np.uint8)

        # Disabled -- no change
        fx.render_post(chars, colors)
        assert np.all(chars == ord("A"))

        # Enable at runtime
        fx.enabled = True
        fx.render_post(chars, colors)
        assert np.all(chars == ord("Z"))


# -- SceneManager integration --


class TestPostFxSceneIntegration:
    def test_postfx_modifies_composited_output(self):
        """PostFx runs after normal sprites and modifies their output."""
        scene = SceneManager(5, 3)
        scene.add(FillSprite(0, 0, 5, 3, char="A", transparent=False))
        scene.add(InvertFx())
        rows, _ = scene.to_grid()
        # FillSprite writes "A" everywhere, InvertFx changes to "Z"
        for row in rows:
            assert all(c == "Z" for c in row)

    def test_postfx_render_does_not_write_in_normal_pass(self):
        """PostFx.render() is a no-op, so it doesn't contribute chars in normal pass."""
        scene = SceneManager(5, 3)
        scene.add(InvertFx())
        rows, _ = scene.to_grid()
        # No normal sprite, PostFx render() is no-op, so all spaces
        for row in rows:
            assert all(c == " " for c in row)

    def test_multiple_postfx_chain_in_priority_order(self):
        """Multiple PostFx effects chain: lower priority runs first."""
        scene = SceneManager(5, 1)
        scene.add(FillSprite(0, 0, 5, 1, char="A", color=1, transparent=False))
        # InvertFx at priority 50: A -> Z
        scene.add(InvertFx(priority=50))
        # ColorShiftFx at priority 60: color 1 -> 11
        scene.add(ColorShiftFx(priority=60))
        rows, colors = scene.to_grid()
        assert all(c == "Z" for c in rows[0])
        assert all(c == 11 for c in colors[0])

    def test_postfx_priority_ordering(self):
        """Later-priority PostFx sees output of earlier-priority PostFx."""

        class MarkFx(PostFx):
            """Replaces all Z chars with Q."""

            def _apply(self, out_chars, out_colors):
                out_chars[out_chars == ord("Z")] = ord("Q")

        scene = SceneManager(3, 1)
        scene.add(FillSprite(0, 0, 3, 1, char="A", transparent=False))
        # InvertFx (priority 50): A -> Z
        scene.add(InvertFx(priority=50))
        # MarkFx (priority 60): Z -> Q (sees output of InvertFx)
        scene.add(MarkFx(priority=60))
        rows, _ = scene.to_grid()
        assert all(c == "Q" for c in rows[0])

    def test_disabled_postfx_skipped_in_scene(self):
        """Disabled PostFx does not modify the composited output."""
        scene = SceneManager(5, 1)
        scene.add(FillSprite(0, 0, 5, 1, char="A", transparent=False))
        scene.add(InvertFx(enabled=False))
        rows, _ = scene.to_grid()
        # InvertFx is disabled, so A stays A
        assert all(c == "A" for c in rows[0])

    def test_dead_postfx_excluded(self):
        """Killed PostFx is not included in the render pass."""
        scene = SceneManager(5, 1)
        scene.add(FillSprite(0, 0, 5, 1, char="A", transparent=False))
        fx = InvertFx()
        scene.add(fx)
        fx.kill()
        rows, _ = scene.to_grid()
        assert all(c == "A" for c in rows[0])

    def test_postfx_with_transparent_normal_sprite(self):
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
