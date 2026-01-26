"""Tests for frame renderer module."""

import pytest

from clarvis.widget.renderer import FrameRenderer
from clarvis.archetypes.weather import WeatherArchetype, Shape, BoundingBox
from clarvis.elements.registry import ElementRegistry
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

    def test_set_status_changes_face_status(self):
        renderer = FrameRenderer()
        renderer.set_status("thinking")
        assert renderer.face.status == "thinking"

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

        initial_index = renderer.face.frame_index
        renderer.tick()

        # Should advance (or wrap around)
        assert renderer.face.frame_index != initial_index or len(renderer.face._frames) <= 1

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


class TestWeatherArchetype:
    """Tests for WeatherArchetype class."""

    @pytest.fixture
    def registry(self):
        """Create and load a registry for testing."""
        reg = ElementRegistry()
        reg.load_all()
        return reg

    def test_create_weather_archetype(self, registry):
        ws = WeatherArchetype(registry, 20, 10)
        assert ws.width == 20
        assert ws.height == 10

    def test_set_weather(self, registry):
        ws = WeatherArchetype(registry, 20, 10)
        ws.set_weather("snow", intensity=0.7)

        assert ws.weather_type == "snow"
        assert ws.intensity == 0.7

    def test_change_weather_clears_particles(self, registry):
        ws = WeatherArchetype(registry, 20, 10)
        ws.set_weather("rain", intensity=1.0)

        # Tick to spawn particles
        for _ in range(20):
            ws.tick()

        particle_count = ws.p_count
        assert particle_count > 0

        # Change weather type
        ws.set_weather("snow", intensity=1.0)
        assert ws.p_count == 0

    def test_tick_spawns_particles(self, registry):
        ws = WeatherArchetype(registry, 20, 10)
        ws.set_weather("rain", intensity=1.0)

        # Tick many times to ensure spawning
        for _ in range(50):
            ws.tick()

        assert ws.p_count > 0

    def test_no_particles_without_weather(self, registry):
        ws = WeatherArchetype(registry, 20, 10)
        # No weather set

        for _ in range(10):
            ws.tick()

        assert ws.p_count == 0

    def test_exclusion_zones(self, registry):
        """Particles should be removed from exclusion zones."""
        ws = WeatherArchetype(registry, 20, 10)
        ws.set_weather("rain", intensity=1.0)

        # Set exclusion zone covering most of the area
        zone = BoundingBox(x=0, y=0, w=20, h=10)
        ws.set_exclusion_zones([zone])

        # Tick and check
        for _ in range(20):
            ws.tick()


class TestAnimationData:
    """Tests for animation data loaded from YAML."""

    @pytest.fixture
    def registry(self):
        reg = ElementRegistry()
        reg.load_all()
        return reg

    def test_all_statuses_have_animations(self, registry):
        """Each status should have animation defined."""
        expected_statuses = ["idle", "thinking", "running", "awaiting", "resting"]
        for status in expected_statuses:
            anim = registry.get('animations', status)
            assert anim is not None, f"Missing animation for {status}"
            assert 'frames' in anim
            assert len(anim['frames']) > 0

    def test_animation_frames_are_valid(self, registry):
        """Animation frames should have eyes and mouth keys."""
        for name in registry.list_names('animations'):
            anim = registry.get('animations', name)
            for frame in anim.get('frames', []):
                assert 'eyes' in frame
                assert 'mouth' in frame


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


class TestElementRegistry:
    """Tests for element registry."""

    @pytest.fixture
    def registry(self):
        reg = ElementRegistry()
        reg.load_all()
        return reg

    def test_loads_eyes(self, registry):
        """Should load eye elements."""
        eyes = registry.list_names('eyes')
        assert 'normal' in eyes
        assert 'closed' in eyes

    def test_loads_mouths(self, registry):
        """Should load mouth elements."""
        mouths = registry.list_names('mouths')
        assert 'neutral' in mouths
        assert 'smile' in mouths

    def test_loads_particles(self, registry):
        """Should load particle elements."""
        particles = registry.list_names('particles')
        assert 'snow_star' in particles
        assert 'rain_drop' in particles

    def test_loads_weather_types(self, registry):
        """Should load weather type definitions."""
        weather = registry.list_names('weather')
        assert 'snow' in weather
        assert 'rain' in weather

    def test_get_returns_element(self, registry):
        """Get should return element definition."""
        elem = registry.get('eyes', 'normal')
        assert elem is not None
        assert 'char' in elem
        assert elem['char'] == 'o'

    def test_get_unknown_returns_none(self, registry):
        """Get unknown element should return None."""
        elem = registry.get('eyes', 'nonexistent')
        assert elem is None
