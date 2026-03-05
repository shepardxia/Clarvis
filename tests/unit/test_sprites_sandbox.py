"""Tests for sprites/sandbox.py — Sandbox pattern (state + step + render)."""

import numpy as np

from clarvis.display.sprites.core import SPACE
from clarvis.display.sprites.sandbox import Sandbox

# -- Trivial engine for testing --


class CounterSandbox(Sandbox):
    """Simple test engine: 2D int array incremented each step."""

    def __init__(self, x, y, width, height, **kwargs):
        super().__init__(x, y, width, height, **kwargs)
        self._state = np.zeros((height, width), dtype=int)
        self._increment = 1

    def step(self) -> None:
        self._state += self._increment

    def state_array(self) -> np.ndarray:
        return self._state

    def configure(self, **config) -> None:
        if "increment" in config:
            self._increment = config["increment"]


# -- Step function --


class TestStep:
    def test_step_called_on_tick(self):
        s = CounterSandbox(0, 0, 3, 2, char_map={0: " ", 1: "#"})
        assert s._state.sum() == 0
        s.tick()
        # All 6 cells should be 1
        assert (s._state == 1).all()

    def test_step_accumulates(self):
        s = CounterSandbox(0, 0, 2, 2)
        s.tick()
        s.tick()
        s.tick()
        assert (s._state == 3).all()
        assert s.age == 3


# -- Char mapping and rendering --


class TestCharMapRender:
    def test_dict_char_map(self):
        s = CounterSandbox(0, 0, 3, 2, char_map={0: ".", 1: "#", 2: "@"})
        # State starts at 0 -> "."
        out_chars = np.full((4, 5), SPACE, dtype=np.int32)
        out_colors = np.zeros((4, 5), dtype=np.int32)
        s.render(out_chars, out_colors)
        assert out_chars[0, 0] == ord(".")
        assert out_chars[1, 2] == ord(".")

        # One tick -> all 1 -> "#"
        s.tick()
        out_chars[:] = SPACE
        s.render(out_chars, out_colors)
        assert out_chars[0, 0] == ord("#")

    def test_gradient_string_char_map(self):
        s = CounterSandbox(0, 0, 2, 1, char_map=" .:#")
        # State = 0 -> char_map[0] = " "
        out_chars = np.full((2, 4), SPACE, dtype=np.int32)
        out_colors = np.zeros((2, 4), dtype=np.int32)
        s.render(out_chars, out_colors)
        # Space + transparent => skipped, so out_chars stays SPACE
        assert out_chars[0, 0] == SPACE

        # Tick twice -> state = 2 -> char_map[2] = ":"
        s.tick()
        s.tick()
        s.render(out_chars, out_colors)
        assert out_chars[0, 0] == ord(":")
        assert out_chars[0, 1] == ord(":")

    def test_gradient_wraps_on_overflow(self):
        s = CounterSandbox(0, 0, 1, 1, char_map="AB")
        # Tick 3 times -> state = 3, 3 % 2 = 1 -> "B"
        s.tick()
        s.tick()
        s.tick()
        out_chars = np.full((2, 2), SPACE, dtype=np.int32)
        out_colors = np.zeros((2, 2), dtype=np.int32)
        s.render(out_chars, out_colors)
        assert out_chars[0, 0] == ord("B")

    def test_missing_key_falls_back_to_space(self):
        s = CounterSandbox(0, 0, 1, 1, char_map={0: "#"})
        s.tick()  # state = 1, not in char_map
        out_chars = np.full((2, 2), ord("X"), dtype=np.int32)
        out_colors = np.zeros((2, 2), dtype=np.int32)
        s.render(out_chars, out_colors)
        # Transparent + space -> skipped, so original "X" remains
        assert out_chars[0, 0] == ord("X")

    def test_no_char_map_renders_space(self):
        s = CounterSandbox(0, 0, 1, 1, char_map=None)
        out_chars = np.full((2, 2), ord("Z"), dtype=np.int32)
        out_colors = np.zeros((2, 2), dtype=np.int32)
        s.render(out_chars, out_colors)
        # Transparent + space -> skipped
        assert out_chars[0, 0] == ord("Z")

    def test_opaque_renders_spaces(self):
        s = CounterSandbox(0, 0, 1, 1, char_map=None, transparent=False)
        out_chars = np.full((2, 2), ord("Z"), dtype=np.int32)
        out_colors = np.zeros((2, 2), dtype=np.int32)
        s.render(out_chars, out_colors)
        # Opaque writes space even over existing content
        assert out_chars[0, 0] == SPACE

    def test_render_respects_position(self):
        s = CounterSandbox(2, 1, 2, 2, char_map={0: "#"})
        out_chars = np.full((5, 6), SPACE, dtype=np.int32)
        out_colors = np.zeros((5, 6), dtype=np.int32)
        s.render(out_chars, out_colors)
        # Should write at (row=1, col=2) through (row=2, col=3)
        assert out_chars[1, 2] == ord("#")
        assert out_chars[1, 3] == ord("#")
        assert out_chars[2, 2] == ord("#")
        assert out_chars[2, 3] == ord("#")
        # Adjacent cells untouched
        assert out_chars[0, 2] == SPACE
        assert out_chars[1, 1] == SPACE


# -- Configure --


class TestConfigure:
    def test_configure_updates_engine(self):
        s = CounterSandbox(0, 0, 2, 2, char_map={0: " ", 5: "#"})
        s.configure(increment=5)
        s.tick()
        assert (s._state == 5).all()

    def test_configure_default_is_noop(self):
        # Base Sandbox.configure() does nothing — should not raise
        s = CounterSandbox(0, 0, 1, 1)
        # Call base configure (CounterSandbox overrides, but test it doesn't break)
        Sandbox.configure(s)


# -- Lifecycle --


class TestLifecycle:
    def test_lifetime_auto_kills(self):
        s = CounterSandbox(0, 0, 1, 1, lifetime=3)
        s.tick()
        s.tick()
        s.tick()
        assert s.alive
        assert s.age == 3
        # Fourth tick exceeds lifetime -> kill
        s.tick()
        assert not s.alive

    def test_no_lifetime_lives_forever(self):
        s = CounterSandbox(0, 0, 1, 1, lifetime=None)
        for _ in range(100):
            s.tick()
        assert s.alive
        assert s.age == 100

    def test_step_not_called_after_kill(self):
        s = CounterSandbox(0, 0, 1, 1, lifetime=1)
        s.tick()  # age=1, step runs, state=1
        assert s.alive
        s.tick()  # age=2 > lifetime=1, killed, step NOT called
        assert not s.alive
        # State should still be 1 (step was not called on the killing tick)
        assert s._state[0, 0] == 1

    def test_age_tracks_ticks(self):
        s = CounterSandbox(0, 0, 1, 1)
        assert s.age == 0
        s.tick()
        assert s.age == 1
        s.tick()
        assert s.age == 2
