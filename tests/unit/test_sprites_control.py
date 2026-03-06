"""Tests for sprites/control.py — Control sprite with click regions."""

import numpy as np

from clarvis.display.sprites.control import Control
from clarvis.display.sprites.core import SPACE

GRID_W, GRID_H = 20, 5


def _make_grids():
    chars = np.full((GRID_H, GRID_W), SPACE, dtype=np.uint32)
    colors = np.zeros((GRID_H, GRID_W), dtype=np.uint8)
    return chars, colors


LABELS = {"enabled": "[MIC]", "disabled": "[---]"}


def test_control_render_and_state():
    """Render at position -> change state -> visibility toggle -> invalid state error."""

    # Phase 1: renders label at position
    ctrl = Control(x=2, y=1, priority=80, labels=LABELS, action_id="mic_toggle")
    chars, colors = _make_grids()
    ctrl.render(chars, colors)
    rendered = "".join(chr(c) for c in chars[1, 2:7])
    assert rendered == "[MIC]"

    # Phase 2: disabled state shows disabled label
    ctrl2 = Control(
        x=0,
        y=0,
        priority=80,
        labels=LABELS,
        action_id="mic_toggle",
        state="disabled",
    )
    chars, colors = _make_grids()
    ctrl2.render(chars, colors)
    rendered = "".join(chr(c) for c in chars[0, 0:5])
    assert rendered == "[---]"

    # Phase 3: invisible writes nothing
    ctrl3 = Control(
        x=0,
        y=0,
        priority=80,
        labels=LABELS,
        action_id="mic",
        visible=False,
    )
    chars, colors = _make_grids()
    ctrl3.render(chars, colors)
    assert np.all(chars == SPACE)
    assert np.all(colors == 0)

    # Phase 4: set_visible toggles rendering on/off
    ctrl4 = Control(x=0, y=0, priority=80, labels=LABELS, action_id="mic")
    ctrl4.set_visible(False)
    chars, colors = _make_grids()
    ctrl4.render(chars, colors)
    assert np.all(chars == SPACE)

    ctrl4.set_visible(True)
    ctrl4.render(chars, colors)
    rendered = "".join(chr(c) for c in chars[0, 0:5])
    assert rendered == "[MIC]"

    # Phase 5: invalid state raises KeyError
    ctrl5 = Control(x=0, y=0, priority=80, labels=LABELS, action_id="mic")
    try:
        ctrl5.set_state("bogus")
        assert False, "Expected KeyError"
    except KeyError:
        pass


def test_control_click_region():
    """Click region returns (row, col, width, height) tuple."""
    ctrl = Control(x=3, y=2, priority=80, labels=LABELS, action_id="mic")
    region = ctrl.click_region()
    assert region == (2, 3, 5, 1)


def test_control_auto_width():
    """Width auto-calculated from longest label, and short labels are padded."""

    # Phase 1: width from longest label
    labels = {"short": "Hi", "long": "Hello!"}
    ctrl = Control(x=0, y=0, priority=80, labels=labels, action_id="greet")
    assert ctrl.bbox.w == 6  # len("Hello!")

    # Phase 2: short label padded to full width
    ctrl2 = Control(
        x=0,
        y=0,
        priority=80,
        labels=labels,
        action_id="greet",
        state="short",
    )
    chars, colors = _make_grids()
    ctrl2.render(chars, colors)
    rendered = "".join(chr(c) for c in chars[0, 0:6])
    assert rendered == "Hi    "
