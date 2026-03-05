"""Tests for Cel sprite (frame animation)."""

import numpy as np

from clarvis.display.sprites.behaviors import Behavior, StaticBehavior
from clarvis.display.sprites.cel import Cel
from clarvis.display.sprites.core import SPACE, BBox
from clarvis.display.sprites.scenes import SceneManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_scene(width=10, height=5):
    return SceneManager(width, height)


def _char_at(out_chars, row, col):
    return chr(out_chars[row, col])


# ---------------------------------------------------------------------------
# Single-frame Cel renders at position
# ---------------------------------------------------------------------------


class TestSingleFrame:
    def test_renders_at_position(self):
        """A single-frame Cel writes its content at (x, y)."""
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
        # tick once to stay at frame 0 (wraps: 1 frame, (0+1)%1 == 0)
        scene.tick()
        chars, colors = scene.render()

        assert _char_at(chars, 1, 2) == "A"
        assert _char_at(chars, 1, 3) == "B"
        assert _char_at(chars, 2, 2) == "C"
        assert _char_at(chars, 2, 3) == "D"

    def test_renders_before_first_tick(self):
        """Frame index starts at 0 — renders correctly without tick."""
        cel = Cel(
            animations={"idle": ["XY"]},
            default_animation="idle",
            x=0,
            y=0,
            width=2,
            height=1,
            priority=0,
        )
        scene = _make_scene(width=5, height=3)
        scene.add(cel)
        chars, _ = scene.render()

        assert _char_at(chars, 0, 0) == "X"
        assert _char_at(chars, 0, 1) == "Y"


# ---------------------------------------------------------------------------
# Multi-frame Cel cycles through frames on tick
# ---------------------------------------------------------------------------


class TestMultiFrameCycling:
    def test_cycles_frames(self):
        """Successive ticks advance through frames and wrap around."""
        frame_a = "A"
        frame_b = "B"
        frame_c = "C"
        cel = Cel(
            animations={"run": [frame_a, frame_b, frame_c]},
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
        cel.render(out_c, out_k)
        assert _char_at(out_c, 0, 0) == "A"

        # tick 1 -> frame_index = 1
        cel.tick()
        out_c.fill(SPACE)
        cel.render(out_c, out_k)
        assert _char_at(out_c, 0, 0) == "B"

        # tick 2 -> frame_index = 2
        cel.tick()
        out_c.fill(SPACE)
        cel.render(out_c, out_k)
        assert _char_at(out_c, 0, 0) == "C"

        # tick 3 -> wraps to frame_index = 0
        cel.tick()
        out_c.fill(SPACE)
        cel.render(out_c, out_k)
        assert _char_at(out_c, 0, 0) == "A"


# ---------------------------------------------------------------------------
# set_animation switches active sequence and resets frame index
# ---------------------------------------------------------------------------


class TestSetAnimation:
    def test_switches_and_resets(self):
        """set_animation changes the active sequence and resets frame_index to 0."""
        cel = Cel(
            animations={
                "idle": ["I1", "I2"],
                "walk": ["W1", "W2"],
            },
            default_animation="idle",
            x=0,
            y=0,
            width=2,
            height=1,
            priority=0,
        )

        # Advance to frame 1 of idle
        cel.tick()
        assert cel.frame_index == 1

        # Switch to walk
        cel.set_animation("walk")
        assert cel.frame_index == 0

        out_c = np.full((3, 5), SPACE, dtype=np.uint32)
        out_k = np.zeros((3, 5), dtype=np.uint8)
        cel.render(out_c, out_k)
        assert _char_at(out_c, 0, 0) == "W"
        assert _char_at(out_c, 0, 1) == "1"

    def test_unknown_animation_raises(self):
        """set_animation with unknown name raises KeyError."""
        cel = Cel(
            animations={"idle": ["X"]},
            default_animation="idle",
            x=0,
            y=0,
            width=1,
            height=1,
            priority=0,
        )
        try:
            cel.set_animation("nonexistent")
            assert False, "Should have raised KeyError"
        except KeyError:
            pass


# ---------------------------------------------------------------------------
# Transparent Cel preserves underlying SPACE chars
# ---------------------------------------------------------------------------


class TestTransparency:
    def test_transparent_preserves_background(self):
        """Through SceneManager, transparent Cel only overwrites non-SPACE cells."""
        # Frame with a SPACE hole: "A B" (middle is space)
        cel = Cel(
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

        # Add a background sprite that fills row 0 with 'Z'
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
        scene.add(bg)
        scene.add(cel)

        chars, _ = scene.render()

        # Non-SPACE cells from the transparent cel overwrite background
        assert _char_at(chars, 0, 0) == "A"
        assert _char_at(chars, 0, 2) == "B"
        # The SPACE cell in the transparent cel preserves the 'Z' from background
        assert _char_at(chars, 0, 1) == "Z"

    def test_opaque_overwrites_everything(self):
        """Opaque Cel overwrites even SPACE cells."""
        cel = Cel(
            animations={"idle": ["A B"]},
            default_animation="idle",
            x=0,
            y=0,
            width=3,
            height=1,
            priority=10,
            transparent=False,
        )

        scene = _make_scene(width=5, height=3)

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
        scene.add(bg)
        scene.add(cel)

        chars, _ = scene.render()

        assert _char_at(chars, 0, 0) == "A"
        # Opaque SPACE overwrites the Z
        assert _char_at(chars, 0, 1) == " "
        assert _char_at(chars, 0, 2) == "B"


# ---------------------------------------------------------------------------
# Accepts precomputed numpy matrices as frames
# ---------------------------------------------------------------------------


class TestNumpyFrames:
    def test_numpy_frame_renders(self):
        """A precomputed numpy array is used directly as a frame."""
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

    def test_mixed_text_and_numpy(self):
        """An animation can mix text strings and numpy arrays."""
        text_frame = "TX"
        np_frame = np.array([[ord("N"), ord("P")]], dtype=np.uint32)
        cel = Cel(
            animations={"idle": [text_frame, np_frame]},
            default_animation="idle",
            x=0,
            y=0,
            width=2,
            height=1,
            priority=0,
        )

        out_c = np.full((3, 5), SPACE, dtype=np.uint32)
        out_k = np.zeros((3, 5), dtype=np.uint8)

        # Frame 0: text
        cel.render(out_c, out_k)
        assert _char_at(out_c, 0, 0) == "T"
        assert _char_at(out_c, 0, 1) == "X"

        # tick -> frame 1: numpy
        cel.tick()
        out_c.fill(SPACE)
        cel.render(out_c, out_k)
        assert _char_at(out_c, 0, 0) == "N"
        assert _char_at(out_c, 0, 1) == "P"

    def test_wrong_shape_raises(self):
        """Numpy frame with mismatched shape raises ValueError."""
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


# ---------------------------------------------------------------------------
# Behavior plugin called on tick
# ---------------------------------------------------------------------------


class TestBehaviorPlugin:
    def test_behavior_called_on_tick(self):
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

    def test_default_behavior_is_static(self):
        """When no behavior is given, StaticBehavior is used (no crash)."""
        cel = Cel(
            animations={"idle": ["X"]},
            default_animation="idle",
            x=0,
            y=0,
            width=1,
            height=1,
            priority=0,
        )
        assert isinstance(cel.behavior, StaticBehavior)
        # Should not raise
        cel.tick()


# ---------------------------------------------------------------------------
# Color application
# ---------------------------------------------------------------------------


class TestColor:
    def test_color_applied_to_non_space(self):
        """Color is applied to non-SPACE cells."""
        cel = Cel(
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
        cel.render(out_c, out_k)

        assert out_k[0, 0] == 42  # 'A' gets color
        assert out_k[0, 1] == 0  # SPACE gets 0
        assert out_k[0, 2] == 42  # 'B' gets color


# ---------------------------------------------------------------------------
# BBox property
# ---------------------------------------------------------------------------


class TestBBox:
    def test_bbox_reflects_position_and_size(self):
        cel = Cel(
            animations={"idle": ["X"]},
            default_animation="idle",
            x=3,
            y=7,
            width=1,
            height=1,
            priority=5,
        )
        b = cel.bbox
        assert b == BBox(3, 7, 1, 1)
        assert b.x2 == 4
        assert b.y2 == 8
