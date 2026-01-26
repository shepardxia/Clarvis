"""Tests for widget modules: colors, config, pipeline, and renderer."""

import pytest

from clarvis.core.colors import load_theme, THEMES, get_merged_theme_colors
from clarvis.widget.config import ThemeConfig, WidgetConfig, DisplayConfig, TestingConfig
from clarvis.widget.pipeline import Layer, RenderPipeline
from clarvis.widget.renderer import FrameRenderer
from clarvis.archetypes.weather import WeatherArchetype, Shape
from clarvis.elements.registry import ElementRegistry


class TestColors:
    def test_theme_loading_and_overrides(self):
        """Test theme loading with overrides."""
        assert load_theme("modern") is True
        assert load_theme("nonexistent") is False

        from clarvis.core import colors
        load_theme("modern", {"thinking": [1.0, 0.0, 0.0]})
        assert colors.STATUS_MAP["thinking"].rgb == (1.0, 0.0, 0.0)

    def test_merged_theme_colors(self):
        """Test theme color merging."""
        result = get_merged_theme_colors("modern", {"thinking": [0.5, 0.5, 0.5]})
        assert result["thinking"] == [0.5, 0.5, 0.5]
        assert result["idle"] == list(THEMES["modern"]["idle"].rgb)


class TestConfig:
    def test_widget_config_roundtrip(self, tmp_path):
        """Test config save/load roundtrip."""
        config = WidgetConfig(ThemeConfig(base="matrix"), DisplayConfig(fps=8), TestingConfig())
        config.save(tmp_path / "config.json")
        loaded = WidgetConfig.load(tmp_path / "config.json")
        assert loaded.theme.base == "matrix"
        assert loaded.display.fps == 8


class TestPipeline:
    def test_layer_compositing(self):
        """Test layer priority compositing."""
        pipeline = RenderPipeline(20, 10)
        bg = pipeline.add_layer("bg", priority=0)
        fg = pipeline.add_layer("fg", priority=10)

        bg.put(5, 2, "B")
        fg.put(5, 2, "F")
        result = pipeline.to_string()
        assert "F" in result.split("\n")[2]  # Foreground wins


class TestRenderer:
    def test_render_dimensions(self):
        """Test renderer output dimensions."""
        renderer = FrameRenderer(width=20, height=10)
        renderer.set_status("idle")
        lines = renderer.render().split("\n")
        assert len(lines) == 10
        assert all(len(line) == 20 for line in lines)


class TestWeatherAndElements:
    @pytest.fixture
    def registry(self):
        reg = ElementRegistry()
        reg.load_all()
        return reg

    def test_weather_particles(self, registry):
        """Test weather system spawns particles."""
        ws = WeatherArchetype(registry, 20, 10)
        ws.set_weather("rain", intensity=1.0)
        for _ in range(50):
            ws.tick()
        assert ws.p_count > 0

    def test_shape_parsing(self):
        """Test shape parsing."""
        assert Shape.parse("*").width == 1
        assert Shape.parse(" ~ \n~~~").height == 2
        with pytest.raises(ValueError):
            Shape.parse("")

    def test_element_registry(self, registry):
        """Test element registry loads elements."""
        assert 'normal' in registry.list_names('eyes')
        assert registry.get('eyes', 'normal')['char'] == 'o'
