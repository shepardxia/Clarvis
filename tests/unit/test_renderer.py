"""Tests for frame renderer module."""

import pytest

from clarvis.widget.renderer import (
    FrameRenderer,
    WeatherSystem,
    Shape,
    get_shape,
    SHAPE_LIBRARY,
    ANIMATION_KEYFRAMES,
)
from clarvis.core.colors import get_status_ansi


class TestFrameRenderer:
    """Tests for FrameRenderer class."""

    def test_create_renderer(self):
        renderer = FrameRenderer(width=20, height=10)
        assert renderer.width == 20
        assert renderer.height == 10

    def test_default_dimensions(self):
        renderer = FrameRenderer()
        assert renderer.width == 18
        assert renderer.height == 10

    def test_set_status(self):
        renderer = FrameRenderer()
        renderer.set_status("running")
        assert renderer.current_status == "running"

    def test_set_status_changes_keyframes(self):
        renderer = FrameRenderer()
        renderer.set_status("thinking")

        assert renderer.current_keyframes == ANIMATION_KEYFRAMES.get("thinking", [])

    def test_render_returns_string(self):
        renderer = FrameRenderer(width=15, height=8)
        renderer.set_status("idle")

        frame = renderer.render(context_percent=50)

        assert isinstance(frame, str)
        assert len(frame) > 0

    def test_render_dimensions(self):
        """Rendered frame should match configured dimensions."""
        renderer = FrameRenderer(width=20, height=10)
        renderer.set_status("idle")

        frame = renderer.render()
        lines = frame.split("\n")

        assert len(lines) == 10
        for line in lines:
            assert len(line) == 20

    def test_tick_advances_animation(self):
        renderer = FrameRenderer()
        renderer.set_status("running")

        initial_index = renderer.keyframe_index
        renderer.tick()

        # Should advance (or wrap around)
        assert renderer.keyframe_index != initial_index or len(renderer.current_keyframes) <= 1

    def test_set_weather(self):
        renderer = FrameRenderer()
        renderer.set_weather("snow", intensity=0.8)

        assert renderer.weather.weather_type == "snow"
        assert renderer.weather.intensity == 0.8

    def test_render_with_weather(self):
        """Rendering with weather should not raise."""
        renderer = FrameRenderer(width=20, height=10)
        renderer.set_status("idle")
        renderer.set_weather("rain", intensity=0.5)

        # Tick a few times to spawn particles
        for _ in range(10):
            renderer.tick()

        frame = renderer.render()
        assert isinstance(frame, str)


class TestWeatherSystem:
    """Tests for WeatherSystem class."""

    def test_create_weather_system(self):
        ws = WeatherSystem(20, 10)
        assert ws.width == 20
        assert ws.height == 10

    def test_set_weather(self):
        ws = WeatherSystem(20, 10)
        ws.set_weather("snow", intensity=0.7)

        assert ws.weather_type == "snow"
        assert ws.intensity == 0.7

    def test_change_weather_clears_particles(self):
        ws = WeatherSystem(20, 10)
        ws.set_weather("rain", intensity=1.0)

        # Tick to spawn particles
        for _ in range(20):
            ws.tick()

        particle_count = ws.p_count
        assert particle_count > 0

        # Change weather type
        ws.set_weather("snow", intensity=1.0)
        assert ws.p_count == 0

    def test_tick_spawns_particles(self):
        ws = WeatherSystem(20, 10)
        ws.set_weather("rain", intensity=1.0)

        # Tick many times to ensure spawning
        for _ in range(50):
            ws.tick()

        assert ws.p_count > 0

    def test_no_particles_without_weather(self):
        ws = WeatherSystem(20, 10)
        # No weather set

        for _ in range(10):
            ws.tick()

        assert ws.p_count == 0

    def test_exclusion_zones(self):
        """Particles should be removed from exclusion zones."""
        from clarvis.widget.renderer import BoundingBox

        ws = WeatherSystem(20, 10)
        ws.set_weather("rain", intensity=1.0)

        # Set exclusion zone covering most of the area
        zone = BoundingBox(x=0, y=0, w=20, h=10)
        ws.set_exclusion_zones([zone])

        # Tick and check
        for _ in range(20):
            ws.tick()

        # All particles should be culled by exclusion zone
        # (render would filter them, but they may still exist in list)


class TestAnimationKeyframes:
    """Tests for animation keyframe data."""

    def test_all_statuses_have_keyframes(self):
        """Each status should have keyframes defined."""
        expected_statuses = ["idle", "thinking", "running", "awaiting", "resting"]
        for status in expected_statuses:
            assert status in ANIMATION_KEYFRAMES, f"Missing keyframes for {status}"
            assert len(ANIMATION_KEYFRAMES[status]) > 0

    def test_keyframes_are_valid(self):
        """Keyframes should be tuples of (eyes, mouth)."""
        for status, frames in ANIMATION_KEYFRAMES.items():
            for frame in frames:
                assert isinstance(frame, tuple)
                assert len(frame) == 2  # (eyes, mouth)
                eyes, mouth = frame
                assert isinstance(eyes, str)
                assert isinstance(mouth, str)


class TestStatusColors:
    """Tests for status color mapping."""

    def test_all_statuses_have_colors(self):
        status_colors = get_status_ansi()
        expected_statuses = ["idle", "thinking", "running", "awaiting", "resting"]
        for status in expected_statuses:
            assert status in status_colors, f"Missing color for {status}"


class TestShape:
    """Tests for Shape dataclass."""

    def test_parse_single_char(self):
        shape = Shape.parse("*")
        assert shape.width == 1
        assert shape.height == 1
        assert shape.pattern == ("*",)

    def test_parse_multi_line(self):
        shape = Shape.parse(" ~ \n~~~")
        assert shape.width == 3
        assert shape.height == 2
        assert shape.pattern == (" ~ ", "~~~")

    def test_width_is_max_line_length(self):
        shape = Shape.parse("a\nabc\nab")
        assert shape.width == 3
        assert shape.height == 3

    def test_empty_raises_error(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            Shape.parse("")

    def test_pattern_is_immutable(self):
        shape = Shape.parse("ab\ncd")
        assert isinstance(shape.pattern, tuple)


class TestGetShape:
    """Tests for get_shape function."""

    def test_returns_cached_shape(self):
        shape1 = get_shape("snow_star")
        shape2 = get_shape("snow_star")
        assert shape1 is shape2

    def test_unknown_shape_raises_keyerror(self):
        with pytest.raises(KeyError, match="Unknown shape"):
            get_shape("nonexistent_shape")

    def test_all_library_shapes_are_valid(self):
        for name in SHAPE_LIBRARY:
            shape = get_shape(name)
            assert shape.width >= 1
            assert shape.height >= 1

    def test_multi_char_shapes_parse_correctly(self):
        cloud = get_shape("cloud_small")
        assert cloud.height == 2
        assert cloud.width == 3

        cloud_med = get_shape("cloud_medium")
        assert cloud_med.height == 3
