"""Tests for Cel sprite (frame animation)."""

import numpy as np

from clarvis.display.sprites.behaviors import Behavior
from clarvis.display.sprites.cel import Cel
from clarvis.display.sprites.core import SPACE
from clarvis.display.sprites.scenes import SceneManager


def _make_scene(width=10, height=5):
    return SceneManager(width, height)


def _char_at(out_chars, row, col):
    return chr(out_chars[row, col])


def test_animation_lifecycle():
    """Full animation lifecycle: render -> cycle frames -> switch animation -> error on unknown."""

    # Phase 1: single-frame Cel renders at position
    cel = Cel(
        animations={"idle": ["AB\nCD"]},
        default_animation="idle",
        x=2,
        y=1,
        width=2,
        height=2,
        priority=0,
    )
    scene = _make_scene(width=10, height=5)
    scene.add(cel)
    scene.tick()
    chars, colors = scene.render()

    assert _char_at(chars, 1, 2) == "A"
    assert _char_at(chars, 1, 3) == "B"
    assert _char_at(chars, 2, 2) == "C"
    assert _char_at(chars, 2, 3) == "D"

    # Phase 2: multi-frame cycling and wrap-around
    cel2 = Cel(
        animations={"run": ["A", "B", "C"]},
        default_animation="run",
        x=0,
        y=0,
        width=1,
        height=1,
        priority=0,
    )

    out_c = np.full((3, 3), SPACE, dtype=np.uint32)
    out_k = np.zeros((3, 3), dtype=np.uint8)

    # Frame index starts at 0
    cel2.render(out_c, out_k)
    assert _char_at(out_c, 0, 0) == "A"

    # tick 1 -> frame_index = 1
    cel2.tick()
    out_c.fill(SPACE)
    cel2.render(out_c, out_k)
    assert _char_at(out_c, 0, 0) == "B"

    # tick 2 -> frame_index = 2
    cel2.tick()
    out_c.fill(SPACE)
    cel2.render(out_c, out_k)
    assert _char_at(out_c, 0, 0) == "C"

    # tick 3 -> wraps to frame_index = 0
    cel2.tick()
    out_c.fill(SPACE)
    cel2.render(out_c, out_k)
    assert _char_at(out_c, 0, 0) == "A"

    # Phase 3: switch animation resets frame index
    cel3 = Cel(
        animations={"idle": ["I1", "I2"], "walk": ["W1", "W2"]},
        default_animation="idle",
        x=0,
        y=0,
        width=2,
        height=1,
        priority=0,
    )
    cel3.tick()
    assert cel3.frame_index == 1

    cel3.set_animation("walk")
    assert cel3.frame_index == 0

    out_c = np.full((3, 5), SPACE, dtype=np.uint32)
    out_k = np.zeros((3, 5), dtype=np.uint8)
    cel3.render(out_c, out_k)
    assert _char_at(out_c, 0, 0) == "W"
    assert _char_at(out_c, 0, 1) == "1"

    # Phase 4: unknown animation raises KeyError
    cel4 = Cel(
        animations={"idle": ["X"]},
        default_animation="idle",
        x=0,
        y=0,
        width=1,
        height=1,
        priority=0,
    )
    try:
        cel4.set_animation("nonexistent")
        assert False, "Should have raised KeyError"
    except KeyError:
        pass


def test_cel_transparency_and_color():
    """Transparency vs opacity, then color masking on non-SPACE cells."""

    # Phase 1: transparent Cel preserves background SPACE cells
    bg = Cel(
        animations={"idle": ["ZZZZZ"]},
        default_animation="idle",
        x=0,
        y=0,
        width=5,
        height=1,
        priority=0,
        transparent=False,
    )
    transparent_cel = Cel(
        animations={"idle": ["A B"]},
        default_animation="idle",
        x=0,
        y=0,
        width=3,
        height=1,
        priority=10,
        transparent=True,
    )

    scene = _make_scene(width=5, height=3)
    scene.add(bg)
    scene.add(transparent_cel)
    chars, _ = scene.render()

    assert _char_at(chars, 0, 0) == "A"
    assert _char_at(chars, 0, 2) == "B"
    # SPACE in transparent cel preserves the 'Z' from background
    assert _char_at(chars, 0, 1) == "Z"

    # Phase 2: opaque Cel overwrites even SPACE cells
    opaque_cel = Cel(
        animations={"idle": ["A B"]},
        default_animation="idle",
        x=0,
        y=0,
        width=3,
        height=1,
        priority=10,
        transparent=False,
    )

    scene2 = _make_scene(width=5, height=3)
    bg2 = Cel(
        animations={"idle": ["ZZZZZ"]},
        default_animation="idle",
        x=0,
        y=0,
        width=5,
        height=1,
        priority=0,
        transparent=False,
    )
    scene2.add(bg2)
    scene2.add(opaque_cel)
    chars2, _ = scene2.render()

    assert _char_at(chars2, 0, 0) == "A"
    assert _char_at(chars2, 0, 1) == " "  # opaque SPACE overwrites Z
    assert _char_at(chars2, 0, 2) == "B"

    # Phase 3: color applied only to non-SPACE cells
    colored_cel = Cel(
        animations={"idle": ["A B"]},
        default_animation="idle",
        x=0,
        y=0,
        width=3,
        height=1,
        priority=0,
        color=42,
    )
    out_c = np.full((3, 5), SPACE, dtype=np.uint32)
    out_k = np.zeros((3, 5), dtype=np.uint8)
    colored_cel.render(out_c, out_k)

    assert out_k[0, 0] == 42  # 'A' gets color
    assert out_k[0, 1] == 0  # SPACE gets 0
    assert out_k[0, 2] == 42  # 'B' gets color


def test_numpy_frames():
    """Valid numpy frames render correctly; mismatched shapes raise ValueError."""

    # Phase 1: numpy array used directly as a frame
    frame = np.array([[ord("N"), ord("P")]], dtype=np.uint32)
    cel = Cel(
        animations={"idle": [frame]},
        default_animation="idle",
        x=1,
        y=0,
        width=2,
        height=1,
        priority=0,
    )
    out_c = np.full((3, 5), SPACE, dtype=np.uint32)
    out_k = np.zeros((3, 5), dtype=np.uint8)
    cel.render(out_c, out_k)

    assert _char_at(out_c, 0, 1) == "N"
    assert _char_at(out_c, 0, 2) == "P"

    # Phase 2: wrong shape raises ValueError
    bad_frame = np.array([[1, 2, 3]], dtype=np.uint32)  # (1, 3) vs expected (1, 2)
    try:
        Cel(
            animations={"idle": [bad_frame]},
            default_animation="idle",
            x=0,
            y=0,
            width=2,
            height=1,
            priority=0,
        )
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_behavior_plugin_on_tick():
    """The behavior's update() is called on each tick."""
    call_log = []

    class TrackingBehavior(Behavior):
        def update(self, sprite, scene):
            call_log.append((sprite, scene))

    behavior = TrackingBehavior()
    cel = Cel(
        animations={"idle": ["X"]},
        default_animation="idle",
        x=0,
        y=0,
        width=1,
        height=1,
        priority=0,
        behavior=behavior,
    )

    cel.tick()
    cel.tick()
    cel.tick()

    assert len(call_log) == 3
    assert all(s is cel for s, _ in call_log)
