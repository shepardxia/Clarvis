"""Tests for canvas module."""

import pytest

from central_hub.widget.canvas import Canvas, Cell, Color, Sprite


class TestCell:
    """Tests for Cell dataclass."""

    def test_default_cell(self):
        cell = Cell()
        assert cell.char == " "
        assert cell.fg == Color.WHITE
        assert cell.bg is None

    def test_custom_cell(self):
        cell = Cell(char="X", fg=Color.RED, bg=Color.BLUE)
        assert cell.char == "X"
        assert cell.fg == Color.RED
        assert cell.bg == Color.BLUE


class TestCanvas:
    """Tests for Canvas operations."""

    def test_create_canvas(self):
        canvas = Canvas(10, 5)
        assert canvas.width == 10
        assert canvas.height == 5

    def test_get_cell_in_bounds(self):
        canvas = Canvas(10, 5)
        canvas.put(3, 2, "A")
        cell = canvas[3, 2]
        assert cell.char == "A"

    def test_get_cell_out_of_bounds(self):
        """Out of bounds access should return empty cell, not raise."""
        canvas = Canvas(10, 5)
        cell = canvas[100, 100]
        assert cell.char == " "

    def test_put_char(self):
        canvas = Canvas(10, 5)
        canvas.put(5, 3, "X", fg=Color.RED)
        assert canvas[5, 3].char == "X"
        assert canvas[5, 3].fg == Color.RED

    def test_put_out_of_bounds_no_error(self):
        """Putting out of bounds should not raise."""
        canvas = Canvas(10, 5)
        # Should not raise
        canvas.put(100, 100, "X")
        canvas.put(-1, -1, "Y")

    def test_render_plain(self):
        canvas = Canvas(3, 2)
        canvas.put(0, 0, "A")
        canvas.put(1, 0, "B")
        canvas.put(2, 0, "C")
        canvas.put(0, 1, "1")
        canvas.put(1, 1, "2")
        canvas.put(2, 1, "3")

        result = canvas.render_plain()
        lines = result.split("\n")
        assert lines[0] == "ABC"
        assert lines[1] == "123"

    def test_clear(self):
        canvas = Canvas(5, 5)
        canvas.put(2, 2, "X")
        canvas.clear()
        assert canvas[2, 2].char == " "


class TestSprite:
    """Tests for Sprite class."""

    def test_create_sprite(self):
        pattern = ["ABC", "DEF"]
        sprite = Sprite(pattern)
        assert sprite.width == 3
        assert sprite.height == 2

    def test_sprite_pattern_access(self):
        pattern = ["AB", "CD"]
        sprite = Sprite(pattern)
        assert sprite.pattern[0][0] == "A"
        assert sprite.pattern[1][1] == "D"

    def test_sprite_dimensions(self):
        pattern = ["AB", "CD"]
        sprite = Sprite(pattern)
        assert sprite.width == 2
        assert sprite.height == 2

    def test_sprite_to_canvas(self):
        pattern = ["##", "##"]
        sprite = Sprite(pattern)
        canvas = sprite.to_canvas(color=Color.GREEN)

        assert canvas.width == 2
        assert canvas.height == 2
        assert canvas[0, 0].char == "#"
        assert canvas[0, 0].fg == Color.GREEN
