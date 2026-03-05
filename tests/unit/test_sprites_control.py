"""Tests for sprites/control.py — Control sprite with click regions."""

import numpy as np

from clarvis.display.sprites.control import Control
from clarvis.display.sprites.core import SPACE, BBox

GRID_W, GRID_H = 20, 5


def _make_grids():
    chars = np.full((GRID_H, GRID_W), SPACE, dtype=np.uint32)
    colors = np.zeros((GRID_H, GRID_W), dtype=np.uint8)
    return chars, colors


LABELS = {"enabled": "[MIC]", "disabled": "[---]"}


class TestControlRender:
    def test_renders_label_at_position(self):
        ctrl = Control(x=2, y=1, priority=80, labels=LABELS, action_id="mic_toggle")
        chars, colors = _make_grids()
        ctrl.render(chars, colors)
        rendered = "".join(chr(c) for c in chars[1, 2:7])
        assert rendered == "[MIC]"

    def test_enabled_state_shows_enabled_label(self):
        ctrl = Control(x=0, y=0, priority=80, labels=LABELS, action_id="mic_toggle")
        chars, colors = _make_grids()
        ctrl.render(chars, colors)
        rendered = "".join(chr(c) for c in chars[0, 0:5])
        assert rendered == "[MIC]"

    def test_disabled_state_shows_disabled_label(self):
        ctrl = Control(
            x=0,
            y=0,
            priority=80,
            labels=LABELS,
            action_id="mic_toggle",
            state="disabled",
        )
        chars, colors = _make_grids()
        ctrl.render(chars, colors)
        rendered = "".join(chr(c) for c in chars[0, 0:5])
        assert rendered == "[---]"

    def test_color_applied_to_non_space_cells(self):
        ctrl = Control(x=0, y=0, priority=80, labels=LABELS, action_id="mic", color=7)
        chars, colors = _make_grids()
        ctrl.render(chars, colors)
        # All 5 chars of "[MIC]" are non-space
        assert all(colors[0, i] == 7 for i in range(5))


class TestClickRegion:
    def test_click_region_returns_tuple(self):
        ctrl = Control(x=3, y=2, priority=80, labels=LABELS, action_id="mic")
        region = ctrl.click_region()
        assert region == (2, 3, 5, 1)  # (row, col, width, height)

    def test_click_region_matches_bbox(self):
        ctrl = Control(x=5, y=4, priority=80, labels=LABELS, action_id="mic")
        region = ctrl.click_region()
        b = ctrl.bbox
        assert region == (b.y, b.x, b.w, b.h)


class TestVisibility:
    def test_invisible_writes_nothing(self):
        ctrl = Control(
            x=0,
            y=0,
            priority=80,
            labels=LABELS,
            action_id="mic",
            visible=False,
        )
        chars, colors = _make_grids()
        ctrl.render(chars, colors)
        # Entire grid should still be SPACE
        assert np.all(chars == SPACE)
        assert np.all(colors == 0)

    def test_set_visible_toggles(self):
        ctrl = Control(x=0, y=0, priority=80, labels=LABELS, action_id="mic")
        ctrl.set_visible(False)
        chars, colors = _make_grids()
        ctrl.render(chars, colors)
        assert np.all(chars == SPACE)

        ctrl.set_visible(True)
        ctrl.render(chars, colors)
        rendered = "".join(chr(c) for c in chars[0, 0:5])
        assert rendered == "[MIC]"


class TestStateToggle:
    def test_set_state_changes_label(self):
        ctrl = Control(x=0, y=0, priority=80, labels=LABELS, action_id="mic")
        ctrl.set_state("disabled")
        chars, colors = _make_grids()
        ctrl.render(chars, colors)
        rendered = "".join(chr(c) for c in chars[0, 0:5])
        assert rendered == "[---]"

    def test_set_state_invalid_raises(self):
        ctrl = Control(x=0, y=0, priority=80, labels=LABELS, action_id="mic")
        try:
            ctrl.set_state("bogus")
            assert False, "Expected KeyError"
        except KeyError:
            pass


class TestWidthAutoCalc:
    def test_width_from_longest_label(self):
        labels = {"short": "Hi", "long": "Hello!"}
        ctrl = Control(x=0, y=0, priority=80, labels=labels, action_id="greet")
        assert ctrl.bbox.w == 6  # len("Hello!")

    def test_width_pads_short_labels(self):
        labels = {"short": "Hi", "long": "Hello!"}
        ctrl = Control(
            x=0,
            y=0,
            priority=80,
            labels=labels,
            action_id="greet",
            state="short",
        )
        chars, colors = _make_grids()
        ctrl.render(chars, colors)
        # "Hi" rendered then padded with SPACE to width 6
        rendered = "".join(chr(c) for c in chars[0, 0:6])
        assert rendered == "Hi    "

    def test_equal_length_labels(self):
        ctrl = Control(x=0, y=0, priority=80, labels=LABELS, action_id="mic")
        assert ctrl.bbox.w == 5  # Both "[MIC]" and "[---]" are 5 chars


class TestBBoxProperty:
    def test_bbox_type_and_values(self):
        ctrl = Control(x=3, y=2, priority=80, labels=LABELS, action_id="mic")
        b = ctrl.bbox
        assert isinstance(b, BBox)
        assert b.x == 3
        assert b.y == 2
        assert b.w == 5
        assert b.h == 1

    def test_bbox_height_always_one(self):
        labels = {"a": "ABCDEFGH"}
        ctrl = Control(x=0, y=0, priority=0, labels=labels, action_id="x")
        assert ctrl.bbox.h == 1


class TestTickNoop:
    def test_tick_does_not_crash(self):
        ctrl = Control(x=0, y=0, priority=80, labels=LABELS, action_id="mic")
        ctrl.tick()  # Should be a no-op
        ctrl.tick(frame=42, dt=0.1)  # With kwargs — still no-op
