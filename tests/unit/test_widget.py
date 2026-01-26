"""Tests for widget modules: colors, config, pipeline, and renderer."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from clarvis.core.colors import (
    ColorDef, Palette, StatusColors, STATUS_MAP, ANSI_COLORS,
    get_status_colors_for_config, get_status_ansi, load_theme,
    get_available_themes, get_current_theme, THEMES, DEFAULT_THEME,
    get_merged_theme_colors,
)
from clarvis.widget.config import (
    ThemeConfig, DisplayConfig, TestingConfig, TokenUsageConfig, WidgetConfig,
)
from clarvis.widget.pipeline import Layer, RenderPipeline
from clarvis.widget.renderer import FrameRenderer
from clarvis.archetypes.weather import WeatherArchetype, Shape, BoundingBox
from clarvis.elements.registry import ElementRegistry


# =============================================================================
# Color Tests
# =============================================================================


class TestColorDef:
    """Tests for ColorDef dataclass."""

    def test_hex_conversion(self):
        assert ColorDef(11, (1.0, 0.87, 0.0)).hex == "#ffdd00"
        assert ColorDef(0, (0.0, 0.0, 0.0)).hex == "#000000"
        assert ColorDef(15, (1.0, 1.0, 1.0)).hex == "#ffffff"

    def test_ansi_codes(self):
        color = ColorDef(11, (1.0, 0.87, 0.0))
        assert color.ansi_fg() == "\033[38;5;11m"
        assert color.ansi_bg() == "\033[48;5;11m"

    def test_frozen(self):
        color = ColorDef(11, (1.0, 0.87, 0.0))
        with pytest.raises(AttributeError):
            color.ansi = 12


class TestPalette:
    """Tests for Palette class."""

    def test_colors_exist(self):
        for attr in ["BLACK", "GRAY", "WHITE", "YELLOW", "GREEN", "BLUE"]:
            assert isinstance(getattr(Palette, attr), ColorDef)

    def test_ansi_codes_valid(self):
        for attr in dir(Palette):
            if not attr.startswith('_'):
                color = getattr(Palette, attr)
                if isinstance(color, ColorDef):
                    assert 0 <= color.ansi <= 255


class TestStatusColors:
    """Tests for StatusColors class."""

    def test_get_known_status(self):
        load_theme("modern")
        assert StatusColors.get("thinking") == THEMES["modern"]["thinking"]

    def test_get_unknown_returns_idle(self):
        load_theme("modern")
        assert StatusColors.get("nonexistent") == STATUS_MAP["idle"]


class TestThemeSystem:
    """Tests for theme loading and management."""

    def test_available_themes(self):
        themes = get_available_themes()
        for t in ["modern", "synthwave", "matrix", "c64"]:
            assert t in themes

    def test_load_theme(self):
        assert load_theme("modern") is True
        assert load_theme("nonexistent") is False

    def test_current_theme(self):
        load_theme("synthwave")
        assert get_current_theme() == "synthwave"

    def test_all_themes_have_all_statuses(self):
        required = ["idle", "resting", "thinking", "running", "awaiting", "offline"]
        for name, colors in THEMES.items():
            for status in required:
                assert status in colors, f"Theme {name} missing {status}"

    def test_load_theme_with_overrides(self):
        from clarvis.core import colors
        load_theme("modern", {"thinking": [1.0, 0.0, 0.0]})
        assert colors.STATUS_MAP["thinking"].rgb == (1.0, 0.0, 0.0)

    def test_get_merged_theme_colors(self):
        result = get_merged_theme_colors("modern", {"thinking": [0.5, 0.5, 0.5]})
        assert result["thinking"] == [0.5, 0.5, 0.5]
        assert result["idle"] == list(THEMES["modern"]["idle"].rgb)


class TestGetStatusColorsForConfig:
    """Tests for config color output."""

    def test_returns_dict(self):
        result = get_status_colors_for_config()
        assert isinstance(result, dict)

    def test_rgb_format(self):
        result = get_status_colors_for_config()
        for status, color in result.items():
            assert all(k in color for k in ["r", "g", "b"])
            assert all(0.0 <= color[k] <= 1.0 for k in ["r", "g", "b"])


# =============================================================================
# Config Tests
# =============================================================================


class TestThemeConfig:
    """Tests for ThemeConfig dataclass."""

    def test_defaults(self):
        config = ThemeConfig()
        assert config.base == DEFAULT_THEME
        assert config.overrides == {}

    def test_to_dict(self):
        config = ThemeConfig(base="synthwave", overrides={"idle": [1.0, 0.0, 0.0]})
        d = config.to_dict()
        assert d["base"] == "synthwave"
        assert d["overrides"] == {"idle": [1.0, 0.0, 0.0]}

    def test_from_dict_legacy_string(self):
        config = ThemeConfig.from_dict("c64")
        assert config.base == "c64"


class TestDisplayConfig:
    """Tests for DisplayConfig dataclass."""

    def test_defaults(self):
        config = DisplayConfig()
        assert config.grid_width == 29
        assert config.fps == 5


class TestTestingConfig:
    """Tests for TestingConfig dataclass."""

    def test_defaults(self):
        config = TestingConfig()
        assert config.enabled is False
        assert config.status == "idle"


class TestTokenUsageConfig:
    """Tests for TokenUsageConfig."""

    def test_defaults(self):
        config = TokenUsageConfig()
        assert config.enabled is True
        assert config.poll_interval == 120

    def test_from_dict(self):
        config = TokenUsageConfig.from_dict({"enabled": False, "poll_interval": 30})
        assert config.enabled is False


class TestWidgetConfig:
    """Tests for WidgetConfig dataclass."""

    def test_to_dict_structure(self):
        config = WidgetConfig(ThemeConfig(), DisplayConfig(), TestingConfig())
        d = config.to_dict()
        assert all(k in d for k in ["theme", "display", "testing", "token_usage"])

    def test_from_dict(self):
        d = {"theme": {"base": "synthwave"}, "display": {"fps": 10}, "testing": {"enabled": True}}
        config = WidgetConfig.from_dict(d)
        assert config.theme.base == "synthwave"
        assert config.display.fps == 10
        assert config.testing.enabled is True

    def test_roundtrip(self):
        original = WidgetConfig(
            ThemeConfig(base="matrix"),
            DisplayConfig(fps=8),
            TestingConfig(enabled=True),
        )
        restored = WidgetConfig.from_dict(original.to_dict())
        assert restored.theme.base == original.theme.base
        assert restored.display.fps == original.display.fps

    def test_save_and_load(self, tmp_path):
        config_file = tmp_path / "config.json"
        config = WidgetConfig(ThemeConfig(), DisplayConfig(), TestingConfig())
        config.save(config_file)
        loaded = WidgetConfig.load(config_file)
        assert loaded.theme.base == config.theme.base

    def test_load_missing_returns_defaults(self, tmp_path):
        config = WidgetConfig.load(tmp_path / "nonexistent.json")
        assert config.theme.base == DEFAULT_THEME


# =============================================================================
# Pipeline Tests
# =============================================================================


class TestLayer:
    """Tests for Layer class."""

    def test_create_layer(self):
        layer = Layer("test", priority=10, width=20, height=10)
        assert layer.name == "test"
        assert layer.priority == 10

    def test_put_char(self):
        layer = Layer("test", priority=0, width=10, height=5)
        layer.put(3, 2, "X", color=1)
        assert layer.chars[2, 3] == ord("X")
        assert layer.colors[2, 3] == 1

    def test_put_out_of_bounds(self):
        layer = Layer("test", priority=0, width=10, height=5)
        layer.put(100, 100, "X")  # Should not raise

    def test_clear(self):
        layer = Layer("test", priority=0, width=10, height=5)
        layer.put(3, 2, "X")
        layer.clear()
        assert layer.chars[2, 3] == 32


class TestRenderPipeline:
    """Tests for RenderPipeline class."""

    def test_create_pipeline(self):
        pipeline = RenderPipeline(20, 10)
        assert pipeline.width == 20
        assert len(pipeline.layers) == 0

    def test_add_layer(self):
        pipeline = RenderPipeline(20, 10)
        layer = pipeline.add_layer("bg", priority=0)
        assert "bg" in pipeline.layers
        assert layer.width == 20

    def test_layer_priority(self):
        pipeline = RenderPipeline(10, 5)
        bg = pipeline.add_layer("bg", priority=0)
        fg = pipeline.add_layer("fg", priority=10)
        bg.put(5, 2, "B")
        fg.put(5, 2, "F")
        result = pipeline.to_string()
        assert "F" in result.split("\n")[2]


# =============================================================================
# Renderer Tests
# =============================================================================


class TestFrameRenderer:
    """Tests for FrameRenderer class."""

    def test_create_renderer(self):
        renderer = FrameRenderer(width=20, height=10)
        assert renderer.width == 20
        assert renderer.height == 10

    def test_set_status(self):
        renderer = FrameRenderer()
        renderer.set_status("running")
        assert renderer.current_status == "running"

    def test_render_returns_string(self):
        renderer = FrameRenderer(width=15, height=8)
        renderer.set_status("idle")
        frame = renderer.render(context_percent=50)
        assert isinstance(frame, str)

    def test_render_dimensions(self):
        renderer = FrameRenderer(width=20, height=10)
        renderer.set_status("idle")
        lines = renderer.render().split("\n")
        assert len(lines) == 10
        for line in lines:
            assert len(line) == 20

    def test_set_weather(self):
        renderer = FrameRenderer()
        renderer.set_weather("snow", intensity=0.8)
        assert renderer.weather.weather_type == "snow"


class TestWeatherArchetype:
    """Tests for WeatherArchetype class."""

    @pytest.fixture
    def registry(self):
        reg = ElementRegistry()
        reg.load_all()
        return reg

    def test_create(self, registry):
        ws = WeatherArchetype(registry, 20, 10)
        assert ws.width == 20

    def test_set_weather(self, registry):
        ws = WeatherArchetype(registry, 20, 10)
        ws.set_weather("snow", intensity=0.7)
        assert ws.weather_type == "snow"

    def test_tick_spawns_particles(self, registry):
        ws = WeatherArchetype(registry, 20, 10)
        ws.set_weather("rain", intensity=1.0)
        for _ in range(50):
            ws.tick()
        assert ws.p_count > 0


class TestShape:
    """Tests for Shape dataclass."""

    def test_parse_single_char(self):
        shape = Shape.parse("*")
        assert shape.width == 1
        assert shape.pattern == ("*",)

    def test_parse_multi_line(self):
        shape = Shape.parse(" ~ \n~~~")
        assert shape.width == 3
        assert shape.height == 2

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            Shape.parse("")


class TestElementRegistry:
    """Tests for element registry."""

    @pytest.fixture
    def registry(self):
        reg = ElementRegistry()
        reg.load_all()
        return reg

    def test_loads_eyes(self, registry):
        assert 'normal' in registry.list_names('eyes')

    def test_loads_particles(self, registry):
        assert 'snow_star' in registry.list_names('particles')

    def test_get_returns_element(self, registry):
        elem = registry.get('eyes', 'normal')
        assert elem['char'] == 'o'

    def test_get_unknown_returns_none(self, registry):
        assert registry.get('eyes', 'nonexistent') is None
