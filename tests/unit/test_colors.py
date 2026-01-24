"""Tests for centralized color definitions."""

import pytest

from clarvis.core.colors import (
    ColorDef,
    Palette,
    StatusColors,
    STATUS_MAP,
    ANSI_COLORS,
    STATUS_ANSI,
    get_status_colors_for_config,
    get_status_ansi,
    load_theme,
    get_available_themes,
    get_current_theme,
    THEMES,
    DEFAULT_THEME,
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
        """Should return color for known status from current theme."""
        # Load modern theme for predictable test
        load_theme("modern")
        assert StatusColors.get("thinking") == THEMES["modern"]["thinking"]
        assert StatusColors.get("running") == THEMES["modern"]["running"]
        assert StatusColors.get("awaiting") == THEMES["modern"]["awaiting"]

    def test_get_unknown_status(self):
        """Should return idle color for unknown status."""
        load_theme("modern")
        assert StatusColors.get("nonexistent") == STATUS_MAP["idle"]

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


class TestThemeSystem:
    """Tests for theme loading and management."""

    def test_get_available_themes(self):
        """Should return list of all theme names."""
        themes = get_available_themes()
        assert isinstance(themes, list)
        assert "modern" in themes
        assert "synthwave" in themes
        assert "crt-amber" in themes
        assert "crt-green" in themes
        assert "c64" in themes
        assert "matrix" in themes

    def test_load_theme_success(self):
        """Loading valid theme should return True."""
        assert load_theme("modern") is True
        assert load_theme("synthwave") is True
        assert load_theme("matrix") is True

    def test_load_theme_invalid(self):
        """Loading invalid theme should return False."""
        assert load_theme("nonexistent_theme") is False

    def test_get_current_theme(self):
        """Should return currently loaded theme name."""
        load_theme("synthwave")
        assert get_current_theme() == "synthwave"
        load_theme("modern")
        assert get_current_theme() == "modern"

    def test_load_theme_updates_status_map(self):
        """Loading theme should update STATUS_MAP with theme colors."""
        # Import module to access current STATUS_MAP after theme load
        from clarvis.core import colors

        load_theme("synthwave")
        assert colors.STATUS_MAP["thinking"] == THEMES["synthwave"]["thinking"]

        load_theme("modern")
        assert colors.STATUS_MAP["thinking"] == THEMES["modern"]["thinking"]

    def test_get_status_ansi(self):
        """Should return status to ANSI code mapping for current theme."""
        load_theme("modern")
        ansi_map = get_status_ansi()
        assert isinstance(ansi_map, dict)
        assert "thinking" in ansi_map
        assert ansi_map["thinking"] == THEMES["modern"]["thinking"].ansi

    def test_all_themes_have_all_statuses(self):
        """Every theme should define all required statuses."""
        required_statuses = ["idle", "resting", "thinking", "running", "executing",
                            "awaiting", "reading", "writing", "reviewing", "offline"]
        for theme_name, theme_colors in THEMES.items():
            for status in required_statuses:
                assert status in theme_colors, f"Theme {theme_name} missing {status}"

    def test_all_theme_colors_valid(self):
        """All theme colors should be valid ColorDef instances."""
        for theme_name, theme_colors in THEMES.items():
            for status, color in theme_colors.items():
                assert isinstance(color, ColorDef), f"{theme_name}.{status} not ColorDef"
                assert 0 <= color.ansi <= 255, f"{theme_name}.{status} ANSI out of range"
                r, g, b = color.rgb
                assert 0.0 <= r <= 1.0, f"{theme_name}.{status} R out of range"
                assert 0.0 <= g <= 1.0, f"{theme_name}.{status} G out of range"
                assert 0.0 <= b <= 1.0, f"{theme_name}.{status} B out of range"

    def test_default_theme_exists(self):
        """DEFAULT_THEME should be a valid theme."""
        assert DEFAULT_THEME in THEMES

    def test_load_theme_with_overrides(self):
        """Loading theme with overrides should apply custom RGB colors."""
        from clarvis.core import colors

        # Define overrides for specific statuses
        overrides = {
            "thinking": [1.0, 0.0, 0.0],  # Override to red
            "running": [0.0, 1.0, 0.0],   # Override to green
        }

        result = load_theme("modern", overrides)
        assert result is True

        # Check that overridden colors have custom RGB but retain original ANSI
        thinking_color = colors.STATUS_MAP["thinking"]
        assert thinking_color.rgb == (1.0, 0.0, 0.0)
        assert thinking_color.ansi == THEMES["modern"]["thinking"].ansi

        running_color = colors.STATUS_MAP["running"]
        assert running_color.rgb == (0.0, 1.0, 0.0)
        assert running_color.ansi == THEMES["modern"]["running"].ansi

        # Non-overridden statuses should keep original theme colors
        idle_color = colors.STATUS_MAP["idle"]
        assert idle_color == THEMES["modern"]["idle"]

    def test_load_theme_with_invalid_override_ignored(self):
        """Overrides with wrong length should be ignored."""
        from clarvis.core import colors

        overrides = {
            "thinking": [1.0, 0.0],  # Only 2 values, should be ignored
            "nonexistent": [1.0, 1.0, 1.0],  # Unknown status, should be ignored
        }

        load_theme("modern", overrides)

        # thinking should keep original color since override is invalid
        assert colors.STATUS_MAP["thinking"] == THEMES["modern"]["thinking"]

    def test_load_theme_with_empty_overrides(self):
        """Empty overrides dict should work like no overrides."""
        from clarvis.core import colors

        load_theme("synthwave", {})
        assert colors.STATUS_MAP["thinking"] == THEMES["synthwave"]["thinking"]


class TestGetMergedThemeColors:
    """Tests for get_merged_theme_colors function."""

    def test_returns_all_statuses(self):
        """Should return all theme statuses as RGB arrays."""
        from clarvis.core.colors import get_merged_theme_colors

        result = get_merged_theme_colors("modern")
        expected_statuses = ["idle", "resting", "thinking", "running", "executing",
                           "awaiting", "reading", "writing", "reviewing", "offline"]
        for status in expected_statuses:
            assert status in result
            assert isinstance(result[status], list)
            assert len(result[status]) == 3

    def test_rgb_values_are_floats(self):
        """RGB values should be floats in 0-1 range."""
        from clarvis.core.colors import get_merged_theme_colors

        result = get_merged_theme_colors("modern")
        for status, rgb in result.items():
            for val in rgb:
                assert isinstance(val, float)
                assert 0.0 <= val <= 1.0

    def test_invalid_theme_falls_back_to_default(self):
        """Invalid theme name should fall back to DEFAULT_THEME."""
        from clarvis.core.colors import get_merged_theme_colors

        result = get_merged_theme_colors("nonexistent_theme")
        expected = get_merged_theme_colors(DEFAULT_THEME)
        assert result == expected

    def test_overrides_applied(self):
        """Overrides should replace base theme colors."""
        from clarvis.core.colors import get_merged_theme_colors

        overrides = {
            "thinking": [0.5, 0.5, 0.5],
            "running": [0.1, 0.2, 0.3],
        }

        result = get_merged_theme_colors("modern", overrides)

        assert result["thinking"] == [0.5, 0.5, 0.5]
        assert result["running"] == [0.1, 0.2, 0.3]
        # Non-overridden should be from base theme
        assert result["idle"] == list(THEMES["modern"]["idle"].rgb)

    def test_invalid_override_ignored(self):
        """Overrides with wrong length should be ignored."""
        from clarvis.core.colors import get_merged_theme_colors

        overrides = {
            "thinking": [0.5, 0.5],  # Only 2 values
        }

        result = get_merged_theme_colors("modern", overrides)

        # Should use base theme color, not invalid override
        assert result["thinking"] == list(THEMES["modern"]["thinking"].rgb)

    def test_none_overrides_same_as_empty(self):
        """None overrides should behave same as empty dict."""
        from clarvis.core.colors import get_merged_theme_colors

        result_none = get_merged_theme_colors("synthwave", None)
        result_empty = get_merged_theme_colors("synthwave", {})

        assert result_none == result_empty
