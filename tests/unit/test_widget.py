"""Tests for widget modules: colors, config, pipeline, and renderer."""

import pytest
from pathlib import Path

from clarvis.core.colors import (
    ColorDef, Palette, StatusColors, STATUS_MAP, load_theme,
    get_available_themes, get_current_theme, THEMES, DEFAULT_THEME,
    get_status_colors_for_config, get_merged_theme_colors,
)
from clarvis.widget.config import (
    ThemeConfig, DisplayConfig, TestingConfig, TokenUsageConfig, WidgetConfig,
)
from clarvis.widget.pipeline import Layer, RenderPipeline
from clarvis.widget.renderer import FrameRenderer
from clarvis.archetypes.weather import WeatherArchetype, Shape
from clarvis.elements.registry import ElementRegistry


class TestColors:
    def test_color_def(self):
        """Test ColorDef hex conversion and ANSI codes."""
        color = ColorDef(11, (1.0, 0.87, 0.0))
        assert color.hex == "#ffdd00"
        assert color.ansi_fg() == "\033[38;5;11m"
        assert color.ansi_bg() == "\033[48;5;11m"
        assert ColorDef(0, (0.0, 0.0, 0.0)).hex == "#000000"

        # Frozen
        with pytest.raises(AttributeError):
            color.ansi = 12

    def test_palette(self):
        """Test Palette colors exist and are valid."""
        for attr in ["BLACK", "GRAY", "WHITE", "YELLOW", "GREEN", "BLUE"]:
            color = getattr(Palette, attr)
            assert isinstance(color, ColorDef)
            assert 0 <= color.ansi <= 255

    def test_themes(self):
        """Test theme system."""
        # Available themes
        themes = get_available_themes()
        for t in ["modern", "synthwave", "matrix", "c64"]:
            assert t in themes

        # Load and check current
        assert load_theme("modern") is True
        assert load_theme("nonexistent") is False
        load_theme("synthwave")
        assert get_current_theme() == "synthwave"

        # All themes have required statuses
        required = ["idle", "resting", "thinking", "running", "awaiting", "offline"]
        for name, colors in THEMES.items():
            for status in required:
                assert status in colors

    def test_status_colors(self):
        """Test StatusColors lookup."""
        load_theme("modern")
        assert StatusColors.get("thinking") == THEMES["modern"]["thinking"]
        assert StatusColors.get("nonexistent") == STATUS_MAP["idle"]

    def test_theme_overrides(self):
        """Test theme loading with overrides."""
        from clarvis.core import colors
        load_theme("modern", {"thinking": [1.0, 0.0, 0.0]})
        assert colors.STATUS_MAP["thinking"].rgb == (1.0, 0.0, 0.0)

        result = get_merged_theme_colors("modern", {"thinking": [0.5, 0.5, 0.5]})
        assert result["thinking"] == [0.5, 0.5, 0.5]
        assert result["idle"] == list(THEMES["modern"]["idle"].rgb)

    def test_config_output(self):
        """Test get_status_colors_for_config output format."""
        result = get_status_colors_for_config()
        assert isinstance(result, dict)
        for status, color in result.items():
            assert all(k in color for k in ["r", "g", "b"])
            assert all(0.0 <= color[k] <= 1.0 for k in ["r", "g", "b"])


class TestConfig:
    def test_theme_config(self):
        """Test ThemeConfig dataclass."""
        config = ThemeConfig()
        assert config.base == DEFAULT_THEME
        assert config.overrides == {}

        config2 = ThemeConfig(base="synthwave", overrides={"idle": [1.0, 0.0, 0.0]})
        d = config2.to_dict()
        assert d["base"] == "synthwave"
        assert d["overrides"] == {"idle": [1.0, 0.0, 0.0]}

        # Legacy string format
        assert ThemeConfig.from_dict("c64").base == "c64"

    def test_display_and_testing_config(self):
        """Test DisplayConfig and TestingConfig defaults."""
        assert DisplayConfig().grid_width == 29
        assert DisplayConfig().fps == 5
        assert TestingConfig().enabled is False
        assert TestingConfig().status == "idle"

    def test_token_usage_config(self):
        """Test TokenUsageConfig."""
        config = TokenUsageConfig()
        assert config.enabled is True
        assert config.poll_interval == 120
        assert TokenUsageConfig.from_dict({"enabled": False}).enabled is False

    def test_widget_config(self):
        """Test WidgetConfig serialization and loading."""
        config = WidgetConfig(ThemeConfig(), DisplayConfig(), TestingConfig())
        d = config.to_dict()
        assert all(k in d for k in ["theme", "display", "testing", "token_usage"])

        # From dict
        d2 = {"theme": {"base": "synthwave"}, "display": {"fps": 10}, "testing": {"enabled": True}}
        config2 = WidgetConfig.from_dict(d2)
        assert config2.theme.base == "synthwave"
        assert config2.display.fps == 10

        # Roundtrip
        original = WidgetConfig(ThemeConfig(base="matrix"), DisplayConfig(fps=8), TestingConfig(enabled=True))
        restored = WidgetConfig.from_dict(original.to_dict())
        assert restored.theme.base == original.theme.base

    def test_widget_config_file_io(self, tmp_path):
        """Test WidgetConfig save/load from file."""
        config_file = tmp_path / "config.json"
        config = WidgetConfig(ThemeConfig(), DisplayConfig(), TestingConfig())
        config.save(config_file)
        loaded = WidgetConfig.load(config_file)
        assert loaded.theme.base == config.theme.base

        # Missing file returns defaults
        config2 = WidgetConfig.load(tmp_path / "nonexistent.json")
        assert config2.theme.base == DEFAULT_THEME


class TestPipeline:
    def test_layer(self):
        """Test Layer class."""
        layer = Layer("test", priority=10, width=20, height=10)
        assert layer.name == "test"
        assert layer.priority == 10

        # Put and clear
        layer.put(3, 2, "X", color=1)
        assert layer.chars[2, 3] == ord("X")
        assert layer.colors[2, 3] == 1

        layer.put(100, 100, "X")  # Out of bounds - no error
        layer.clear()
        assert layer.chars[2, 3] == 32

    def test_render_pipeline(self):
        """Test RenderPipeline compositing."""
        pipeline = RenderPipeline(20, 10)
        assert pipeline.width == 20
        assert len(pipeline.layers) == 0

        # Add layers
        bg = pipeline.add_layer("bg", priority=0)
        fg = pipeline.add_layer("fg", priority=10)
        assert "bg" in pipeline.layers
        assert bg.width == 20

        # Priority compositing
        bg.put(5, 2, "B")
        fg.put(5, 2, "F")
        result = pipeline.to_string()
        assert "F" in result.split("\n")[2]


class TestRenderer:
    def test_frame_renderer(self):
        """Test FrameRenderer basics."""
        renderer = FrameRenderer(width=20, height=10)
        assert renderer.width == 20
        assert renderer.height == 10

        renderer.set_status("running")
        assert renderer.current_status == "running"

        frame = renderer.render(context_percent=50)
        assert isinstance(frame, str)

        # Dimensions
        lines = renderer.render().split("\n")
        assert len(lines) == 10
        for line in lines:
            assert len(line) == 20

    def test_weather_setting(self):
        """Test setting weather on renderer."""
        renderer = FrameRenderer()
        renderer.set_weather("snow", intensity=0.8)
        assert renderer.weather.weather_type == "snow"


class TestWeatherAndElements:
    @pytest.fixture
    def registry(self):
        reg = ElementRegistry()
        reg.load_all()
        return reg

    def test_weather_archetype(self, registry):
        """Test WeatherArchetype creation and particle spawning."""
        ws = WeatherArchetype(registry, 20, 10)
        assert ws.width == 20

        ws.set_weather("snow", intensity=0.7)
        assert ws.weather_type == "snow"

        ws.set_weather("rain", intensity=1.0)
        for _ in range(50):
            ws.tick()
        assert ws.p_count > 0

    def test_shape(self):
        """Test Shape parsing."""
        shape = Shape.parse("*")
        assert shape.width == 1
        assert shape.pattern == ("*",)

        shape2 = Shape.parse(" ~ \n~~~")
        assert shape2.width == 3
        assert shape2.height == 2

        with pytest.raises(ValueError):
            Shape.parse("")

    def test_element_registry(self, registry):
        """Test ElementRegistry loading and access."""
        assert 'normal' in registry.list_names('eyes')
        assert 'snow_star' in registry.list_names('particles')

        elem = registry.get('eyes', 'normal')
        assert elem['char'] == 'o'
        assert registry.get('eyes', 'nonexistent') is None
