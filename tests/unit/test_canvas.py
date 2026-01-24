"""Tests for canvas and brush system."""

import pytest

from clarvis.widget.canvas import (
    Color,
    Cell,
    Canvas,
    Brush,
    Sprite,
    FaceBuilder,
    SPRITES,
)


class TestColor:
    """Tests for Color enum."""

    def test_ansi_fg_code(self):
        """Should return ANSI foreground escape code."""
        assert Color.RED.ansi_fg() == "\033[38;5;1m"
        assert Color.BRIGHT_GREEN.ansi_fg() == "\033[38;5;10m"

    def test_ansi_bg_code(self):
        """Should return ANSI background escape code."""
        assert Color.BLUE.ansi_bg() == "\033[48;5;4m"
        assert Color.BRIGHT_YELLOW.ansi_bg() == "\033[48;5;11m"

    def test_reset_fg_code(self):
        """Reset should return reset escape code for fg."""
        assert Color.RESET.ansi_fg() == "\033[0m"

    def test_reset_bg_code(self):
        """Reset should return reset escape code for bg."""
        assert Color.RESET.ansi_bg() == "\033[0m"

    def test_all_colors_have_valid_values(self):
        """All colors should have integer values."""
        for color in Color:
            assert isinstance(color.value, int)


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

    def test_render_without_bg(self):
        """Render should include fg code, char, and reset."""
        cell = Cell("A", Color.GREEN)
        rendered = cell.render()
        assert Color.GREEN.ansi_fg() in rendered
        assert "A" in rendered
        assert Color.RESET.ansi_fg() in rendered

    def test_render_with_bg(self):
        """Render should include bg code when set."""
        cell = Cell("B", Color.WHITE, Color.RED)
        rendered = cell.render()
        assert Color.RED.ansi_bg() in rendered
        assert Color.WHITE.ansi_fg() in rendered
        assert "B" in rendered


class TestCanvas:
    """Tests for Canvas operations."""

    def test_create_canvas(self):
        canvas = Canvas(10, 5)
        assert canvas.width == 10
        assert canvas.height == 5

    def test_cells_initialized_empty(self):
        """All cells should start as spaces."""
        c = Canvas(3, 3)
        for y in range(3):
            for x in range(3):
                assert c[x, y].char == " "

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

    def test_setitem_in_bounds(self):
        """Should set cell at position."""
        c = Canvas(5, 5)
        c[2, 2] = Cell("Y", Color.RED)
        assert c[2, 2].char == "Y"
        assert c[2, 2].fg == Color.RED

    def test_setitem_out_of_bounds_ignored(self):
        """Out of bounds set should be silently ignored."""
        c = Canvas(5, 5)
        c[10, 10] = Cell("Z")  # Should not raise

    def test_put_char(self):
        canvas = Canvas(10, 5)
        canvas.put(5, 3, "X", fg=Color.RED)
        assert canvas[5, 3].char == "X"
        assert canvas[5, 3].fg == Color.RED

    def test_put_with_bg(self):
        """Put should accept background color."""
        c = Canvas(5, 5)
        c.put(0, 0, "@", Color.WHITE, Color.RED)
        assert c[0, 0].bg == Color.RED

    def test_put_out_of_bounds_no_error(self):
        """Putting out of bounds should not raise."""
        canvas = Canvas(10, 5)
        # Should not raise
        canvas.put(100, 100, "X")
        canvas.put(-1, -1, "Y")

    def test_fill(self):
        """Fill should fill rectangle with character."""
        c = Canvas(10, 10)
        c.fill(2, 2, 3, 2, "*", Color.YELLOW)
        # Check filled area
        for y in range(2, 4):
            for x in range(2, 5):
                assert c[x, y].char == "*"
                assert c[x, y].fg == Color.YELLOW
        # Check outside is still empty
        assert c[0, 0].char == " "
        assert c[5, 2].char == " "

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

    def test_render_with_colors(self):
        """Render should produce ANSI string with newlines."""
        c = Canvas(3, 2)
        c.put(0, 0, "A", Color.RED)
        c.put(1, 0, "B", Color.GREEN)
        rendered = c.render()
        assert "\n" in rendered
        assert "A" in rendered
        assert "B" in rendered
        assert "\033" in rendered  # Has ANSI codes

    def test_clear(self):
        canvas = Canvas(5, 5)
        canvas.put(2, 2, "X")
        canvas.clear()
        assert canvas[2, 2].char == " "

    def test_composite(self):
        """Composite should overlay canvas onto another."""
        base = Canvas(10, 10)
        base.fill(0, 0, 10, 10, ".")

        overlay = Canvas(3, 3)
        overlay.fill(0, 0, 3, 3, "#", Color.RED)

        base.composite(overlay, 2, 2)

        # Check overlay area
        for y in range(2, 5):
            for x in range(2, 5):
                assert base[x, y].char == "#"
        # Check outside
        assert base[0, 0].char == "."

    def test_composite_transparent(self):
        """Composite should skip transparent characters."""
        base = Canvas(5, 5)
        base.fill(0, 0, 5, 5, ".")

        overlay = Canvas(3, 3)
        overlay.put(0, 0, "X")
        overlay.put(2, 2, "Y")
        # Middle stays as space (transparent)

        base.composite(overlay, 1, 1)

        assert base[1, 1].char == "X"
        assert base[3, 3].char == "Y"
        assert base[2, 2].char == "."  # Transparent, so base shows through


class TestBrush:
    """Tests for Brush drawing primitives."""

    def test_point(self):
        """Point should draw single character."""
        c = Canvas(5, 5)
        Brush.point(c, 2, 2, "@", Color.MAGENTA)
        assert c[2, 2].char == "@"
        assert c[2, 2].fg == Color.MAGENTA

    def test_hline(self):
        """Hline should draw horizontal line."""
        c = Canvas(10, 5)
        Brush.hline(c, 1, 2, 5, "-", Color.BLUE)
        for x in range(1, 6):
            assert c[x, 2].char == "-"
        assert c[0, 2].char == " "
        assert c[6, 2].char == " "

    def test_vline(self):
        """Vline should draw vertical line."""
        c = Canvas(5, 10)
        Brush.vline(c, 2, 1, 5, "|", Color.GREEN)
        for y in range(1, 6):
            assert c[2, y].char == "|"
        assert c[2, 0].char == " "
        assert c[2, 6].char == " "

    def test_rect(self):
        """Rect should draw filled rectangle."""
        c = Canvas(10, 10)
        Brush.rect(c, 2, 2, 3, 2, "#", Color.RED)
        for y in range(2, 4):
            for x in range(2, 5):
                assert c[x, y].char == "#"

    def test_rect_outline(self):
        """Rect outline should draw box with corners."""
        c = Canvas(10, 10)
        Brush.rect_outline(c, 1, 1, 5, 3, Color.WHITE)
        # Corners
        assert c[1, 1].char == "┌"
        assert c[5, 1].char == "┐"
        assert c[1, 3].char == "└"
        assert c[5, 3].char == "┘"
        # Horizontal edges
        assert c[2, 1].char == "─"
        assert c[3, 3].char == "─"
        # Vertical edges
        assert c[1, 2].char == "│"
        assert c[5, 2].char == "│"

    def test_rounded_rect_corners(self):
        """Rounded rect should use block corner characters."""
        c = Canvas(10, 10)
        Brush.rounded_rect(c, 1, 1, 4, 3, Color.BLUE, fill=False)
        assert c[1, 1].char == Brush.CORNER_UL
        assert c[4, 1].char == Brush.CORNER_UR
        assert c[1, 3].char == Brush.CORNER_LL
        assert c[4, 3].char == Brush.CORNER_LR

    def test_rounded_rect_filled(self):
        """Rounded rect with fill should fill interior."""
        c = Canvas(10, 10)
        Brush.rounded_rect(c, 1, 1, 5, 4, Color.GREEN, fill=True)
        # Interior should be filled
        assert c[2, 2].char == Brush.FULL
        assert c[3, 2].char == Brush.FULL

    def test_text(self):
        """Text should draw string horizontally."""
        c = Canvas(20, 5)
        Brush.text(c, 2, 1, "Hello", Color.YELLOW)
        assert c[2, 1].char == "H"
        assert c[3, 1].char == "e"
        assert c[4, 1].char == "l"
        assert c[5, 1].char == "l"
        assert c[6, 1].char == "o"

    def test_text_centered(self):
        """Text centered should center on canvas width."""
        c = Canvas(11, 3)
        Brush.text_centered(c, 1, "Hi", Color.WHITE)
        # "Hi" is 2 chars, canvas is 11, so x = (11-2)//2 = 4
        assert c[4, 1].char == "H"
        assert c[5, 1].char == "i"

    def test_progress_bar_empty(self):
        """Progress bar at 0% should be all empty chars."""
        c = Canvas(15, 3)
        Brush.progress_bar(c, 1, 1, 10, 0, filled_char="=", empty_char="-")
        for x in range(1, 11):
            assert c[x, 1].char == "-"

    def test_progress_bar_full(self):
        """Progress bar at 100% should be all filled chars."""
        c = Canvas(15, 3)
        Brush.progress_bar(c, 1, 1, 10, 100, filled_char="=", empty_char="-")
        for x in range(1, 11):
            assert c[x, 1].char == "="

    def test_progress_bar_partial(self):
        """Progress bar at 50% should be half filled."""
        c = Canvas(15, 3)
        Brush.progress_bar(c, 0, 0, 10, 50, filled_char="#", empty_char=".")
        for x in range(5):
            assert c[x, 0].char == "#"
        for x in range(5, 10):
            assert c[x, 0].char == "."


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

    def test_sprite_variable_width(self):
        """Sprite width should be max line length."""
        sprite = Sprite(["A", "BCDE", "FG"])
        assert sprite.width == 4
        assert sprite.height == 3

    def test_empty_sprite(self):
        """Empty sprite should have 0 dimensions."""
        sprite = Sprite([])
        assert sprite.width == 0
        assert sprite.height == 0

    def test_sprite_to_canvas(self):
        pattern = ["##", "##"]
        sprite = Sprite(pattern)
        canvas = sprite.to_canvas(color=Color.GREEN)

        assert canvas.width == 2
        assert canvas.height == 2
        assert canvas[0, 0].char == "#"
        assert canvas[0, 0].fg == Color.GREEN

    def test_stamp(self):
        """Stamp should draw sprite onto canvas."""
        sprite = Sprite(["XY", "ZW"])
        c = Canvas(10, 10)
        sprite.stamp(c, 2, 3, Color.BLUE)
        assert c[2, 3].char == "X"
        assert c[3, 3].char == "Y"
        assert c[2, 4].char == "Z"
        assert c[3, 4].char == "W"

    def test_stamp_respects_transparent(self):
        """Stamp should skip transparent characters."""
        sprite = Sprite(["X ", " Y"])
        c = Canvas(5, 5)
        c.fill(0, 0, 5, 5, ".")
        sprite.stamp(c, 1, 1, transparent=" ")
        assert c[1, 1].char == "X"
        assert c[2, 1].char == "."  # Transparent, base shows
        assert c[1, 2].char == "."  # Transparent, base shows
        assert c[2, 2].char == "Y"


class TestPrebuiltSprites:
    """Tests for pre-built sprites."""

    def test_sprites_dict_exists(self):
        """SPRITES dict should have entries."""
        assert len(SPRITES) > 0

    def test_snowflake_sprite(self):
        """Snowflake sprite should be single character."""
        assert "snowflake" in SPRITES
        assert SPRITES["snowflake"].width == 1
        assert SPRITES["snowflake"].height == 1

    def test_raindrop_sprite(self):
        """Raindrop sprite should be single character."""
        assert "raindrop" in SPRITES
        assert SPRITES["raindrop"].pattern == ["|"]


class TestFaceBuilder:
    """Tests for FaceBuilder class."""

    def test_build_creates_face(self):
        """Build should create a face on canvas."""
        c = Canvas(20, 10)
        FaceBuilder.build(c, 2, 2, Color.WHITE, eyes="normal", mouth="neutral", status="idle")
        # Check top border exists
        assert c[2, 2].char == "+"
        # Check face is 11 chars wide
        assert c[12, 2].char == "+"

    def test_build_different_eyes(self):
        """Different eye types should produce different characters."""
        c1 = Canvas(20, 10)
        c2 = Canvas(20, 10)
        FaceBuilder.build(c1, 0, 0, eyes="normal")
        FaceBuilder.build(c2, 0, 0, eyes="closed")
        # Eye row
        line1 = c1.render_plain().split("\n")[1]
        line2 = c2.render_plain().split("\n")[1]
        assert line1 != line2

    def test_build_different_mouths(self):
        """Different mouth types should produce different characters."""
        c1 = Canvas(20, 10)
        c2 = Canvas(20, 10)
        FaceBuilder.build(c1, 0, 0, mouth="smile")
        FaceBuilder.build(c2, 0, 0, mouth="open")
        # Mouth row
        line1 = c1.render_plain().split("\n")[2]
        line2 = c2.render_plain().split("\n")[2]
        assert line1 != line2

    def test_build_different_statuses(self):
        """Different statuses should produce different borders."""
        c1 = Canvas(20, 10)
        c2 = Canvas(20, 10)
        FaceBuilder.build(c1, 0, 0, status="idle")
        FaceBuilder.build(c2, 0, 0, status="thinking")
        # Top border row
        line1 = c1.render_plain().split("\n")[0]
        line2 = c2.render_plain().split("\n")[0]
        assert line1 != line2

    def test_eyes_dict_coverage(self):
        """All eyes in dict should work."""
        for eye_name in FaceBuilder.EYES:
            c = Canvas(20, 10)
            FaceBuilder.build(c, 0, 0, eyes=eye_name)

    def test_mouths_dict_coverage(self):
        """All mouths in dict should work."""
        for mouth_name in FaceBuilder.MOUTHS:
            c = Canvas(20, 10)
            FaceBuilder.build(c, 0, 0, mouth=mouth_name)

    def test_statuses_dict_coverage(self):
        """All statuses in dict should work."""
        for status in FaceBuilder.BORDERS:
            c = Canvas(20, 10)
            FaceBuilder.build(c, 0, 0, status=status)
