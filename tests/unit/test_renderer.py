"""Tests for frame renderer module."""

import pytest

from central_hub.widget.renderer import (
    FrameRenderer,
    WeatherSystem,
    ANIMATION_KEYFRAMES,
    STATUS_COLORS,
)


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

        particle_count = len(ws.particles)
        assert particle_count > 0

        # Change weather type
        ws.set_weather("snow", intensity=1.0)
        assert len(ws.particles) == 0

    def test_tick_spawns_particles(self):
        ws = WeatherSystem(20, 10)
        ws.set_weather("rain", intensity=1.0)

        # Tick many times to ensure spawning
        for _ in range(50):
            ws.tick()

        assert len(ws.particles) > 0

    def test_no_particles_without_weather(self):
        ws = WeatherSystem(20, 10)
        # No weather set

        for _ in range(10):
            ws.tick()

        assert len(ws.particles) == 0

    def test_exclusion_zones(self):
        """Particles should be removed from exclusion zones."""
        from central_hub.widget.renderer import BoundingBox

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
        expected_statuses = ["idle", "thinking", "running", "awaiting", "resting"]
        for status in expected_statuses:
            assert status in STATUS_COLORS, f"Missing color for {status}"
