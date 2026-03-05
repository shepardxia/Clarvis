"""Tests for sprites/reel.py — Reel sprite with text viewport and temporal effects."""

import numpy as np

from clarvis.display.sprites.core import SPACE, BBox
from clarvis.display.sprites.reel import Reel, ReelMode, _word_wrap

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_arrays(width=40, height=20):
    """Create fresh output arrays matching SceneManager conventions."""
    out_chars = np.full((height, width), SPACE, dtype=np.uint32)
    out_colors = np.zeros((height, width), dtype=np.uint8)
    return out_chars, out_colors


def read_row(out_chars, row, x, width):
    """Extract a string from out_chars at (row, x..x+width)."""
    codes = out_chars[row, x : x + width]
    return "".join(chr(c) for c in codes)


# ---------------------------------------------------------------------------
# _word_wrap
# ---------------------------------------------------------------------------


class TestWordWrap:
    def test_simple_fits(self):
        assert _word_wrap("hello", 10) == ["hello"]

    def test_wraps_at_space(self):
        lines = _word_wrap("hello world", 7)
        assert lines == ["hello", "world"]

    def test_hard_break_long_word(self):
        lines = _word_wrap("abcdefghij", 4)
        assert lines == ["abcd", "efgh", "ij"]

    def test_newlines_preserved(self):
        lines = _word_wrap("a\nb\nc", 10)
        assert lines == ["a", "b", "c"]

    def test_empty_string(self):
        assert _word_wrap("", 10) == [""]

    def test_zero_width(self):
        assert _word_wrap("hello", 0) == []

    def test_mixed_short_and_long(self):
        lines = _word_wrap("hi superlongword ok", 5)
        assert lines == ["hi", "super", "longw", "ord", "ok"]


# ---------------------------------------------------------------------------
# STATIC mode
# ---------------------------------------------------------------------------


class TestReelStatic:
    def test_renders_within_viewport(self):
        r = Reel(x=2, y=1, width=10, height=3, priority=0, mode=ReelMode.STATIC, content="hello")
        out_c, out_k = make_arrays()
        r.render(out_c, out_k)

        row_text = read_row(out_c, 1, 2, 5)
        assert row_text == "hello"

    def test_wraps_long_text(self):
        r = Reel(x=0, y=0, width=5, height=3, priority=0, mode=ReelMode.STATIC, content="hello world")
        out_c, out_k = make_arrays()
        r.render(out_c, out_k)

        assert read_row(out_c, 0, 0, 5) == "hello"
        assert read_row(out_c, 1, 0, 5) == "world"

    def test_clips_to_viewport_height(self):
        r = Reel(x=0, y=0, width=5, height=1, priority=0, mode=ReelMode.STATIC, content="hello world again")
        out_c, out_k = make_arrays()
        r.render(out_c, out_k)

        # Only first line visible
        assert read_row(out_c, 0, 0, 5) == "hello"
        # Second line not rendered
        row1 = read_row(out_c, 1, 0, 5)
        assert row1 == "     "

    def test_bbox(self):
        r = Reel(x=3, y=5, width=10, height=4, priority=7)
        assert r.bbox == BBox(3, 5, 10, 4)


# ---------------------------------------------------------------------------
# REVEAL mode
# ---------------------------------------------------------------------------


class TestReelReveal:
    def test_starts_empty(self):
        r = Reel(x=0, y=0, width=10, height=3, priority=0, mode=ReelMode.REVEAL, content="hello")
        out_c, out_k = make_arrays()
        r.render(out_c, out_k)

        # Nothing revealed yet
        assert read_row(out_c, 0, 0, 5) == "     "

    def test_advances_on_tick(self):
        r = Reel(x=0, y=0, width=10, height=3, priority=0, mode=ReelMode.REVEAL, content="hello", reveal_speed=2)
        r.tick()  # reveal_pos = 2
        out_c, out_k = make_arrays()
        r.render(out_c, out_k)

        assert read_row(out_c, 0, 0, 5) == "he   "

    def test_full_reveal_after_enough_ticks(self):
        r = Reel(x=0, y=0, width=10, height=3, priority=0, mode=ReelMode.REVEAL, content="hello", reveal_speed=1)
        for _ in range(10):
            r.tick()
        out_c, out_k = make_arrays()
        r.render(out_c, out_k)

        assert read_row(out_c, 0, 0, 5) == "hello"

    def test_set_reveal_position(self):
        r = Reel(x=0, y=0, width=10, height=3, priority=0, mode=ReelMode.REVEAL, content="hello")
        r.set_reveal_position(3)
        out_c, out_k = make_arrays()
        r.render(out_c, out_k)

        assert read_row(out_c, 0, 0, 5) == "hel  "

    def test_reveal_across_lines(self):
        r = Reel(x=0, y=0, width=5, height=3, priority=0, mode=ReelMode.REVEAL, content="hello world")
        # "hello" (5 chars) + "world" (5 chars)
        r.set_reveal_position(7)
        out_c, out_k = make_arrays()
        r.render(out_c, out_k)

        # First line fully revealed
        assert read_row(out_c, 0, 0, 5) == "hello"
        # Second line: 7 - 5 = 2 chars visible
        assert read_row(out_c, 1, 0, 5) == "wo   "

    def test_set_reveal_position_negative_clamped(self):
        r = Reel(x=0, y=0, width=10, height=3, priority=0, mode=ReelMode.REVEAL, content="hello")
        r.set_reveal_position(-5)
        assert r._reveal_pos == 0


# ---------------------------------------------------------------------------
# SCROLL mode
# ---------------------------------------------------------------------------


class TestReelScroll:
    def test_starts_at_top(self):
        r = Reel(x=0, y=0, width=10, height=2, priority=0, mode=ReelMode.SCROLL, content="line1\nline2\nline3\nline4")
        out_c, out_k = make_arrays()
        r.render(out_c, out_k)

        assert read_row(out_c, 0, 0, 5) == "line1"
        assert read_row(out_c, 1, 0, 5) == "line2"

    def test_scrolls_on_tick(self):
        r = Reel(x=0, y=0, width=10, height=2, priority=0, mode=ReelMode.SCROLL, content="line1\nline2\nline3\nline4")
        r.tick()  # scroll_offset = 1
        out_c, out_k = make_arrays()
        r.render(out_c, out_k)

        assert read_row(out_c, 0, 0, 5) == "line2"
        assert read_row(out_c, 1, 0, 5) == "line3"

    def test_clips_at_bottom(self):
        r = Reel(x=0, y=0, width=10, height=2, priority=0, mode=ReelMode.SCROLL, content="line1\nline2\nline3")
        # Max offset = 3 - 2 = 1
        r.tick()  # offset 1
        r.tick()  # should stay at 1
        out_c, out_k = make_arrays()
        r.render(out_c, out_k)

        assert read_row(out_c, 0, 0, 5) == "line2"
        assert read_row(out_c, 1, 0, 5) == "line3"

    def test_viewport_clips_rows(self):
        r = Reel(x=0, y=0, width=10, height=2, priority=0, mode=ReelMode.SCROLL, content="a\nb\nc\nd\ne")
        out_c, out_k = make_arrays()
        r.render(out_c, out_k)

        # Only 2 rows visible
        assert read_row(out_c, 0, 0, 1) == "a"
        assert read_row(out_c, 1, 0, 1) == "b"
        # Row 2 should be blank
        assert read_row(out_c, 2, 0, 1) == " "


# ---------------------------------------------------------------------------
# MARQUEE mode
# ---------------------------------------------------------------------------


class TestReelMarquee:
    def test_initial_render(self):
        r = Reel(x=0, y=0, width=10, height=1, priority=0, mode=ReelMode.MARQUEE, content="ABCDE")
        out_c, out_k = make_arrays()
        r.render(out_c, out_k)

        # offset=0, so starts from beginning of "ABCDE   " (looped text)
        row = read_row(out_c, 0, 0, 10)
        assert row.startswith("ABCDE")

    def test_scrolls_horizontally(self):
        r = Reel(x=0, y=0, width=5, height=1, priority=0, mode=ReelMode.MARQUEE, content="ABCDE", scroll_speed=1)
        r.tick()  # offset = 1
        out_c, out_k = make_arrays()
        r.render(out_c, out_k)

        row = read_row(out_c, 0, 0, 5)
        assert row == "BCDE "  # "ABCDE   " shifted by 1

    def test_wraps_around(self):
        r = Reel(x=0, y=0, width=5, height=1, priority=0, mode=ReelMode.MARQUEE, content="AB", scroll_speed=1)
        # "AB   " (len=5) — loops after 5 ticks
        # Tick 5 times to wrap
        for _ in range(5):
            r.tick()
        out_c, out_k = make_arrays()
        r.render(out_c, out_k)

        row = read_row(out_c, 0, 0, 5)
        # Offset 5 mod 5 == 0 → back to start
        assert row.startswith("AB")


# ---------------------------------------------------------------------------
# set_content
# ---------------------------------------------------------------------------


class TestSetContent:
    def test_updates_buffer(self):
        r = Reel(x=0, y=0, width=10, height=3, priority=0, mode=ReelMode.STATIC, content="old")
        r.set_content("new")
        out_c, out_k = make_arrays()
        r.render(out_c, out_k)

        assert read_row(out_c, 0, 0, 3) == "new"

    def test_resets_reveal_position(self):
        r = Reel(x=0, y=0, width=10, height=3, priority=0, mode=ReelMode.REVEAL, content="first")
        r.set_reveal_position(5)
        r.set_content("second")
        assert r._reveal_pos == 0

    def test_resets_scroll_offset(self):
        r = Reel(x=0, y=0, width=10, height=2, priority=0, mode=ReelMode.SCROLL, content="a\nb\nc")
        r.tick()
        r.set_content("x\ny\nz")
        assert r._scroll_offset == 0

    def test_resets_marquee_offset(self):
        r = Reel(x=0, y=0, width=10, height=1, priority=0, mode=ReelMode.MARQUEE, content="abc")
        r.tick()
        r.set_content("xyz")
        assert r._marquee_offset == 0


# ---------------------------------------------------------------------------
# Transparency — SPACE chars
# ---------------------------------------------------------------------------


class TestTransparency:
    def test_space_cells_remain_space(self):
        """SPACE cells in the rendered frame should be SPACE (not overwritten).
        Transparency is handled by SceneManager, but Reel should emit SPACE
        for blank areas so the compositing mask works correctly."""
        r = Reel(x=0, y=0, width=10, height=2, priority=0, mode=ReelMode.STATIC, content="hi")
        out_c, out_k = make_arrays()
        r.render(out_c, out_k)

        # "hi" occupies cells 0,1 — rest should be SPACE
        assert out_c[0, 0] == ord("h")
        assert out_c[0, 1] == ord("i")
        assert out_c[0, 2] == SPACE
        assert out_c[0, 9] == SPACE
        # Second row entirely SPACE
        assert out_c[1, 0] == SPACE

    def test_color_only_on_non_space(self):
        """Color should only be set for non-SPACE cells."""
        r = Reel(x=0, y=0, width=10, height=2, priority=0, mode=ReelMode.STATIC, content="ab", color=42)
        out_c, out_k = make_arrays()
        r.render(out_c, out_k)

        assert out_k[0, 0] == 42
        assert out_k[0, 1] == 42
        assert out_k[0, 2] == 0  # SPACE cell — no color
        assert out_k[1, 0] == 0

    def test_transparent_default(self):
        r = Reel(x=0, y=0, width=5, height=1, priority=0)
        assert r.transparent is True


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_content(self):
        r = Reel(x=0, y=0, width=10, height=3, priority=0, content="")
        out_c, out_k = make_arrays()
        r.render(out_c, out_k)
        # All SPACE
        assert np.all(out_c == SPACE)

    def test_kill(self):
        r = Reel(x=0, y=0, width=5, height=1, priority=0)
        assert r.alive
        r.kill()
        assert not r.alive

    def test_tick_static_is_noop(self):
        r = Reel(x=0, y=0, width=10, height=3, priority=0, mode=ReelMode.STATIC, content="hello")
        r.tick()
        # No state change — just verifying no error
        out_c, out_k = make_arrays()
        r.render(out_c, out_k)
        assert read_row(out_c, 0, 0, 5) == "hello"
