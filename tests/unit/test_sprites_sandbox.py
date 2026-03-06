"""Tests for sprites/sandbox.py — Sandbox pattern (state + step + render)."""

import numpy as np

from clarvis.display.sprites.core import SPACE
from clarvis.display.sprites.sandbox import Sandbox


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


def test_char_map_rendering():
    """Char map variants and edge cases: dict map, gradient string, overflow wrap,
    missing key fallback, opaque spaces, and position offset."""

    # Phase 1: dict char map — state 0 maps to ".", state 1 maps to "#"
    s = CounterSandbox(0, 0, 3, 2, char_map={0: ".", 1: "#", 2: "@"})
    out_chars = np.full((4, 5), SPACE, dtype=np.int32)
    out_colors = np.zeros((4, 5), dtype=np.int32)
    s.render(out_chars, out_colors)
    assert out_chars[0, 0] == ord(".")
    assert out_chars[1, 2] == ord(".")

    s.tick()
    out_chars[:] = SPACE
    s.render(out_chars, out_colors)
    assert out_chars[0, 0] == ord("#")

    # Phase 2: gradient string char map — index into string
    s2 = CounterSandbox(0, 0, 2, 1, char_map=" .:#")
    out_chars = np.full((2, 4), SPACE, dtype=np.int32)
    out_colors = np.zeros((2, 4), dtype=np.int32)
    s2.render(out_chars, out_colors)
    # State 0 -> space + transparent => skipped
    assert out_chars[0, 0] == SPACE

    s2.tick()
    s2.tick()
    s2.render(out_chars, out_colors)
    assert out_chars[0, 0] == ord(":")
    assert out_chars[0, 1] == ord(":")

    # Phase 3: gradient wraps on overflow
    s3 = CounterSandbox(0, 0, 1, 1, char_map="AB")
    s3.tick()
    s3.tick()
    s3.tick()  # state = 3, 3 % 2 = 1 -> "B"
    out_chars = np.full((2, 2), SPACE, dtype=np.int32)
    out_colors = np.zeros((2, 2), dtype=np.int32)
    s3.render(out_chars, out_colors)
    assert out_chars[0, 0] == ord("B")

    # Phase 4: missing key falls back to space (transparent preserves background)
    s4 = CounterSandbox(0, 0, 1, 1, char_map={0: "#"})
    s4.tick()  # state = 1, not in char_map
    out_chars = np.full((2, 2), ord("X"), dtype=np.int32)
    out_colors = np.zeros((2, 2), dtype=np.int32)
    s4.render(out_chars, out_colors)
    assert out_chars[0, 0] == ord("X")  # transparent + space -> original preserved

    # Phase 5: opaque renders spaces over existing content
    s5 = CounterSandbox(0, 0, 1, 1, char_map=None, transparent=False)
    out_chars = np.full((2, 2), ord("Z"), dtype=np.int32)
    out_colors = np.zeros((2, 2), dtype=np.int32)
    s5.render(out_chars, out_colors)
    assert out_chars[0, 0] == SPACE

    # Phase 6: render respects position offset
    s6 = CounterSandbox(2, 1, 2, 2, char_map={0: "#"})
    out_chars = np.full((5, 6), SPACE, dtype=np.int32)
    out_colors = np.zeros((5, 6), dtype=np.int32)
    s6.render(out_chars, out_colors)
    assert out_chars[1, 2] == ord("#")
    assert out_chars[1, 3] == ord("#")
    assert out_chars[2, 2] == ord("#")
    assert out_chars[2, 3] == ord("#")
    # Adjacent cells untouched
    assert out_chars[0, 2] == SPACE
    assert out_chars[1, 1] == SPACE


def test_sandbox_lifecycle():
    """Lifetime auto-kills and step is not called after kill."""

    # Phase 1: lifetime auto-kill triggers after exceeding lifetime
    s = CounterSandbox(0, 0, 1, 1, lifetime=3)
    s.tick()
    s.tick()
    s.tick()
    assert s.alive
    assert s.age == 3

    s.tick()  # fourth tick exceeds lifetime -> killed
    assert not s.alive

    # Phase 2: step is NOT called on the killing tick
    s2 = CounterSandbox(0, 0, 1, 1, lifetime=1)
    s2.tick()  # age=1, step runs, state=1
    assert s2.alive
    s2.tick()  # age=2 > lifetime=1, killed, step NOT called
    assert not s2.alive
    assert s2._state[0, 0] == 1  # state unchanged on killing tick
