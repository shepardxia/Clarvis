"""Property-based tests using Hypothesis."""

import pytest
from hypothesis import given, strategies as st, settings, assume

from central_hub.services.weather import calculate_intensity, WEATHER_CODE_INTENSITY
from central_hub.widget.canvas import Canvas, Cell, Color
from central_hub.widget.pipeline import Layer


class TestIntensityProperties:
    """Property tests for weather intensity calculation."""

    @given(
        weather_code=st.sampled_from(list(WEATHER_CODE_INTENSITY.keys())),
        wind_speed=st.floats(min_value=0, max_value=200, allow_nan=False),
        precipitation=st.floats(min_value=0, max_value=100, allow_nan=False),
        snowfall=st.floats(min_value=0, max_value=50, allow_nan=False),
    )
    def test_intensity_always_in_range(self, weather_code, wind_speed, precipitation, snowfall):
        """Intensity should always be between 0 and 1 for any valid input."""
        intensity = calculate_intensity(weather_code, wind_speed, precipitation, snowfall)
        assert 0 <= intensity <= 1

    @given(
        weather_code=st.sampled_from(list(WEATHER_CODE_INTENSITY.keys())),
        wind_speed=st.floats(min_value=0, max_value=200, allow_nan=False),
        precipitation=st.floats(min_value=0, max_value=100, allow_nan=False),
        snowfall=st.floats(min_value=0, max_value=50, allow_nan=False),
    )
    def test_intensity_is_float(self, weather_code, wind_speed, precipitation, snowfall):
        """Intensity should always be a float."""
        intensity = calculate_intensity(weather_code, wind_speed, precipitation, snowfall)
        assert isinstance(intensity, float)

    @given(
        wind_speed=st.floats(min_value=0, max_value=100, allow_nan=False),
    )
    def test_higher_wind_increases_intensity(self, wind_speed):
        """Higher wind speed should never decrease intensity (all else equal)."""
        low = calculate_intensity(0, 0, 0, 0)
        high = calculate_intensity(0, wind_speed, 0, 0)
        assert high >= low

    @given(
        precipitation=st.floats(min_value=0, max_value=50, allow_nan=False),
    )
    def test_higher_precip_increases_intensity(self, precipitation):
        """Higher precipitation should never decrease intensity (all else equal)."""
        low = calculate_intensity(61, 10, 0, 0)
        high = calculate_intensity(61, 10, precipitation, 0)
        assert high >= low


class TestCanvasProperties:
    """Property tests for Canvas operations."""

    @given(
        width=st.integers(min_value=1, max_value=100),
        height=st.integers(min_value=1, max_value=100),
        x=st.integers(min_value=-100, max_value=200),
        y=st.integers(min_value=-100, max_value=200),
    )
    def test_canvas_get_never_raises(self, width, height, x, y):
        """Getting any position should never raise, even out of bounds."""
        canvas = Canvas(width, height)
        cell = canvas[x, y]
        assert isinstance(cell, Cell)

    @given(
        width=st.integers(min_value=1, max_value=100),
        height=st.integers(min_value=1, max_value=100),
        x=st.integers(min_value=-100, max_value=200),
        y=st.integers(min_value=-100, max_value=200),
        char=st.text(min_size=1, max_size=1),
    )
    def test_canvas_put_never_raises(self, width, height, x, y, char):
        """Putting at any position should never raise, even out of bounds."""
        canvas = Canvas(width, height)
        # Should not raise
        canvas.put(x, y, char)

    @given(
        width=st.integers(min_value=1, max_value=50),
        height=st.integers(min_value=1, max_value=50),
    )
    def test_canvas_render_plain_dimensions(self, width, height):
        """render_plain should produce correct dimensions."""
        canvas = Canvas(width, height)
        result = canvas.render_plain()
        lines = result.split("\n")

        assert len(lines) == height
        for line in lines:
            assert len(line) == width

    @given(
        width=st.integers(min_value=1, max_value=50),
        height=st.integers(min_value=1, max_value=50),
        x=st.integers(min_value=0, max_value=49),
        y=st.integers(min_value=0, max_value=49),
    )
    def test_canvas_roundtrip(self, width, height, x, y):
        """Put then get should return the same value (if in bounds)."""
        assume(x < width and y < height)

        canvas = Canvas(width, height)
        canvas.put(x, y, "X")
        cell = canvas[x, y]

        assert cell.char == "X"


class TestLayerProperties:
    """Property tests for Layer operations."""

    @given(
        width=st.integers(min_value=1, max_value=100),
        height=st.integers(min_value=1, max_value=100),
        x=st.integers(min_value=-100, max_value=200),
        y=st.integers(min_value=-100, max_value=200),
    )
    def test_layer_put_never_raises(self, width, height, x, y):
        """Putting at any position should never raise."""
        layer = Layer("test", priority=0, width=width, height=height)
        # Should not raise
        layer.put(x, y, "X")

    @given(
        width=st.integers(min_value=1, max_value=50),
        height=st.integers(min_value=1, max_value=50),
    )
    def test_layer_clear_resets_all(self, width, height):
        """Clear should reset all cells."""
        layer = Layer("test", priority=0, width=width, height=height)

        # Put some chars
        layer.put(0, 0, "A")
        layer.put(width - 1, height - 1, "Z")

        layer.clear()

        # All should be spaces (32)
        assert (layer.chars == 32).all()


class TestHistoryProperties:
    """Property tests for history buffer behavior."""

    @given(
        entries=st.lists(
            st.tuples(
                st.sampled_from(["running", "thinking", "awaiting", "idle"]),
                st.floats(min_value=0, max_value=100, allow_nan=False),
            ),
            min_size=0,
            max_size=100,
        ),
    )
    @settings(max_examples=50, deadline=1000)
    def test_history_never_exceeds_limit(self, entries):
        """History buffers should never exceed HISTORY_SIZE."""
        from central_hub.daemon import CentralHubDaemon
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            daemon = CentralHubDaemon(
                status_raw_file=tmp_path / "status.json",
                hub_data_file=tmp_path / "hub.json",
                output_file=tmp_path / "widget.json",
            )

            for status, context in entries:
                daemon._add_to_history("test-session", status, context)

            session = daemon.sessions.get("test-session", {})
            status_history = session.get("status_history", [])
            context_history = session.get("context_history", [])

            assert len(status_history) <= daemon.HISTORY_SIZE
            assert len(context_history) <= daemon.HISTORY_SIZE
