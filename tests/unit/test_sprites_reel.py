"""Tests for sprites/reel.py — Reel sprite with text viewport and temporal effects."""

import numpy as np

from clarvis.display.sprites.core import SPACE
from clarvis.display.sprites.reel import Reel, ReelMode, _word_wrap


def make_arrays(width=40, height=20):
    """Create fresh output arrays matching SceneManager conventions."""
    out_chars = np.full((height, width), SPACE, dtype=np.uint32)
    out_colors = np.zeros((height, width), dtype=np.uint8)
    return out_chars, out_colors


def read_row(out_chars, row, x, width):
    """Extract a string from out_chars at (row, x..x+width)."""
    codes = out_chars[row, x : x + width]
    return "".join(chr(c) for c in codes)


def test_word_wrap():
    """Word wrap algorithm: fits, wraps at space, hard breaks, newlines, empty, zero width."""

    # simple text fits in one line
    assert _word_wrap("hello", 10) == ["hello"]

    # wraps at space boundary
    lines = _word_wrap("hello world", 7)
    assert lines == ["hello", "world"]

    # hard break on long words
    lines = _word_wrap("abcdefghij", 4)
    assert lines == ["abcd", "efgh", "ij"]

    # newlines preserved as line breaks
    lines = _word_wrap("a\nb\nc", 10)
    assert lines == ["a", "b", "c"]

    # empty string produces single empty line
    assert _word_wrap("", 10) == [""]

    # zero width produces empty list
    assert _word_wrap("hello", 0) == []


def test_reel_static_rendering():
    """Static mode: renders within viewport, wraps long text, clips to viewport height."""

    # Phase 1: renders within viewport at position
    r = Reel(x=2, y=1, width=10, height=3, priority=0, mode=ReelMode.STATIC, content="hello")
    out_c, out_k = make_arrays()
    r.render(out_c, out_k)
    assert read_row(out_c, 1, 2, 5) == "hello"

    # Phase 2: wraps long text across lines
    r2 = Reel(x=0, y=0, width=5, height=3, priority=0, mode=ReelMode.STATIC, content="hello world")
    out_c, out_k = make_arrays()
    r2.render(out_c, out_k)
    assert read_row(out_c, 0, 0, 5) == "hello"
    assert read_row(out_c, 1, 0, 5) == "world"

    # Phase 3: clips to viewport height
    r3 = Reel(x=0, y=0, width=5, height=1, priority=0, mode=ReelMode.STATIC, content="hello world again")
    out_c, out_k = make_arrays()
    r3.render(out_c, out_k)
    assert read_row(out_c, 0, 0, 5) == "hello"
    assert read_row(out_c, 1, 0, 5) == "     "  # clipped


def test_reel_reveal_behavior():
    """Reveal mode lifecycle: starts empty -> advances on tick -> reveals across lines ->
    negative position clamped."""

    # Phase 1: starts with nothing revealed
    r = Reel(x=0, y=0, width=10, height=3, priority=0, mode=ReelMode.REVEAL, content="hello")
    out_c, out_k = make_arrays()
    r.render(out_c, out_k)
    assert read_row(out_c, 0, 0, 5) == "     "

    # Phase 2: advances on tick
    r2 = Reel(x=0, y=0, width=10, height=3, priority=0, mode=ReelMode.REVEAL, content="hello", reveal_speed=2)
    r2.tick()  # reveal_pos = 2
    out_c, out_k = make_arrays()
    r2.render(out_c, out_k)
    assert read_row(out_c, 0, 0, 5) == "he   "

    # Phase 3: reveal across lines
    r3 = Reel(x=0, y=0, width=5, height=3, priority=0, mode=ReelMode.REVEAL, content="hello world")
    r3.set_reveal_position(7)
    out_c, out_k = make_arrays()
    r3.render(out_c, out_k)
    assert read_row(out_c, 0, 0, 5) == "hello"
    assert read_row(out_c, 1, 0, 5) == "wo   "  # 7 - 5 = 2 chars visible

    # Phase 4: negative position clamped to 0
    r4 = Reel(x=0, y=0, width=10, height=3, priority=0, mode=ReelMode.REVEAL, content="hello")
    r4.set_reveal_position(-5)
    assert r4._reveal_pos == 0


def test_reel_scroll_behavior():
    """Scroll mode lifecycle: starts at top -> scrolls on tick -> clips at bottom."""

    content = "line1\nline2\nline3\nline4"

    # Phase 1: starts at top
    r = Reel(x=0, y=0, width=10, height=2, priority=0, mode=ReelMode.SCROLL, content=content)
    out_c, out_k = make_arrays()
    r.render(out_c, out_k)
    assert read_row(out_c, 0, 0, 5) == "line1"
    assert read_row(out_c, 1, 0, 5) == "line2"

    # Phase 2: scrolls on tick
    r.tick()  # scroll_offset = 1
    out_c, out_k = make_arrays()
    r.render(out_c, out_k)
    assert read_row(out_c, 0, 0, 5) == "line2"
    assert read_row(out_c, 1, 0, 5) == "line3"

    # Phase 3: clips at bottom (3 lines, height=2, max offset=1)
    r2 = Reel(x=0, y=0, width=10, height=2, priority=0, mode=ReelMode.SCROLL, content="line1\nline2\nline3")
    r2.tick()  # offset 1
    r2.tick()  # should stay at 1
    out_c, out_k = make_arrays()
    r2.render(out_c, out_k)
    assert read_row(out_c, 0, 0, 5) == "line2"
    assert read_row(out_c, 1, 0, 5) == "line3"


def test_reel_marquee_behavior():
    """Marquee mode lifecycle: initial render -> scrolls horizontally -> wraps around."""

    # Phase 1: initial render starts from beginning
    r = Reel(x=0, y=0, width=10, height=1, priority=0, mode=ReelMode.MARQUEE, content="ABCDE")
    out_c, out_k = make_arrays()
    r.render(out_c, out_k)
    row = read_row(out_c, 0, 0, 10)
    assert row.startswith("ABCDE")

    # Phase 2: scrolls horizontally
    r2 = Reel(x=0, y=0, width=5, height=1, priority=0, mode=ReelMode.MARQUEE, content="ABCDE", scroll_speed=1)
    r2.tick()  # offset = 1
    out_c, out_k = make_arrays()
    r2.render(out_c, out_k)
    row = read_row(out_c, 0, 0, 5)
    assert row == "BCDE "

    # Phase 3: wraps around after full cycle
    r3 = Reel(x=0, y=0, width=5, height=1, priority=0, mode=ReelMode.MARQUEE, content="AB", scroll_speed=1)
    for _ in range(5):
        r3.tick()
    out_c, out_k = make_arrays()
    r3.render(out_c, out_k)
    row = read_row(out_c, 0, 0, 5)
    assert row.startswith("AB")  # offset 5 mod 5 == 0 -> back to start


def test_reel_content_and_transparency():
    """Content updates, state resets, transparency contract, color masking, and empty content."""

    # Phase 1: set_content updates rendered buffer
    r = Reel(x=0, y=0, width=10, height=3, priority=0, mode=ReelMode.STATIC, content="old")
    r.set_content("new")
    out_c, out_k = make_arrays()
    r.render(out_c, out_k)
    assert read_row(out_c, 0, 0, 3) == "new"

    # Phase 2: set_content resets reveal position
    r2 = Reel(x=0, y=0, width=10, height=3, priority=0, mode=ReelMode.REVEAL, content="first")
    r2.set_reveal_position(5)
    r2.set_content("second")
    assert r2._reveal_pos == 0

    # Phase 3: SPACE cells remain SPACE (transparency contract)
    r3 = Reel(x=0, y=0, width=10, height=2, priority=0, mode=ReelMode.STATIC, content="hi")
    out_c, out_k = make_arrays()
    r3.render(out_c, out_k)
    assert out_c[0, 0] == ord("h")
    assert out_c[0, 1] == ord("i")
    assert out_c[0, 2] == SPACE
    assert out_c[0, 9] == SPACE
    assert out_c[1, 0] == SPACE  # second row entirely SPACE

    # Phase 4: color only on non-SPACE cells
    r4 = Reel(x=0, y=0, width=10, height=2, priority=0, mode=ReelMode.STATIC, content="ab", color=42)
    out_c, out_k = make_arrays()
    r4.render(out_c, out_k)
    assert out_k[0, 0] == 42
    assert out_k[0, 1] == 42
    assert out_k[0, 2] == 0  # SPACE cell — no color
    assert out_k[1, 0] == 0

    # Phase 5: empty content renders all SPACE
    r5 = Reel(x=0, y=0, width=10, height=3, priority=0, content="")
    out_c, out_k = make_arrays()
    r5.render(out_c, out_k)
    assert np.all(out_c == SPACE)
