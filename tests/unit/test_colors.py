"""Tests for centralized color definitions."""

import pytest

from central_hub.core.colors import (
    ColorDef,
    Palette,
    StatusColors,
    STATUS_MAP,
    ANSI_COLORS,
    STATUS_ANSI,
    get_status_colors_for_config,
)


class TestColorDef:
    """Tests for ColorDef dataclass."""

    def test_hex_property(self):
        """Should convert RGB to hex string."""
        color = ColorDef(11, (1.0, 0.87, 0.0))
        assert color.hex == "#ffdd00"  # 0.87 * 255 = 221.85 -> 221 = 0xdd

    def test_hex_black(self):
        """Should handle black (0, 0, 0)."""
        color = ColorDef(0, (0.0, 0.0, 0.0))
        assert color.hex == "#000000"

    def test_hex_white(self):
        """Should handle white (1, 1, 1)."""
        color = ColorDef(15, (1.0, 1.0, 1.0))
        assert color.hex == "#ffffff"

    def test_ansi_fg(self):
        """Should return ANSI foreground escape code."""
        color = ColorDef(11, (1.0, 0.87, 0.0))
        assert color.ansi_fg() == "\033[38;5;11m"

    def test_ansi_bg(self):
        """Should return ANSI background escape code."""
        color = ColorDef(11, (1.0, 0.87, 0.0))
        assert color.ansi_bg() == "\033[48;5;11m"

    def test_frozen(self):
        """ColorDef should be immutable."""
        color = ColorDef(11, (1.0, 0.87, 0.0))
        with pytest.raises(AttributeError):
            color.ansi = 12


class TestPalette:
    """Tests for Palette class."""

    def test_palette_colors_exist(self):
        """All palette colors should be ColorDef instances."""
        assert isinstance(Palette.BLACK, ColorDef)
        assert isinstance(Palette.GRAY, ColorDef)
        assert isinstance(Palette.WHITE, ColorDef)
        assert isinstance(Palette.YELLOW, ColorDef)
        assert isinstance(Palette.GREEN, ColorDef)
        assert isinstance(Palette.BLUE, ColorDef)
        assert isinstance(Palette.MAGENTA, ColorDef)
        assert isinstance(Palette.RED, ColorDef)

    def test_ansi_codes_in_valid_range(self):
        """ANSI codes should be 0-255."""
        for attr in dir(Palette):
            if not attr.startswith('_'):
                color = getattr(Palette, attr)
                if isinstance(color, ColorDef):
                    assert 0 <= color.ansi <= 255


class TestStatusColors:
    """Tests for StatusColors class."""

    def test_get_known_status(self):
        """Should return color for known status."""
        assert StatusColors.get("thinking") == Palette.YELLOW
        assert StatusColors.get("running") == Palette.GREEN
        assert StatusColors.get("awaiting") == Palette.BLUE

    def test_get_unknown_status(self):
        """Should return IDLE for unknown status."""
        assert StatusColors.get("nonexistent") == StatusColors.IDLE

    def test_all_statuses_mapped(self):
        """All status attributes should be in STATUS_MAP."""
        for status in ["idle", "resting", "thinking", "running", "executing",
                       "awaiting", "reading", "writing", "reviewing", "offline"]:
            assert status in STATUS_MAP


class TestAnsiColors:
    """Tests for ANSI_COLORS dict."""

    def test_all_colors_are_integers(self):
        """ANSI codes should be integers."""
        for name, code in ANSI_COLORS.items():
            assert isinstance(code, int), f"{name} should be int"

    def test_expected_colors_present(self):
        """Expected color names should be present."""
        expected = ["gray", "white", "yellow", "green", "blue", "magenta"]
        for name in expected:
            assert name in ANSI_COLORS


class TestStatusAnsi:
    """Tests for STATUS_ANSI dict."""

    def test_all_statuses_mapped(self):
        """All statuses should have ANSI codes."""
        expected = ["idle", "resting", "thinking", "running", "executing",
                    "awaiting", "reading", "writing", "reviewing", "offline"]
        for status in expected:
            assert status in STATUS_ANSI
            assert isinstance(STATUS_ANSI[status], int)


class TestGetStatusColorsForConfig:
    """Tests for get_status_colors_for_config function."""

    def test_returns_dict(self):
        """Should return a dictionary."""
        result = get_status_colors_for_config()
        assert isinstance(result, dict)

    def test_all_statuses_present(self):
        """All statuses should be in result."""
        result = get_status_colors_for_config()
        expected = ["idle", "resting", "thinking", "running", "executing",
                    "awaiting", "reading", "writing", "reviewing", "offline"]
        for status in expected:
            assert status in result

    def test_rgb_format(self):
        """Each status should have r, g, b keys with float values."""
        result = get_status_colors_for_config()
        for status, color in result.items():
            assert "r" in color
            assert "g" in color
            assert "b" in color
            assert isinstance(color["r"], float)
            assert isinstance(color["g"], float)
            assert isinstance(color["b"], float)
            assert 0.0 <= color["r"] <= 1.0
            assert 0.0 <= color["g"] <= 1.0
            assert 0.0 <= color["b"] <= 1.0
