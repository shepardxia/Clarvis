"""Property-based tests using Hypothesis."""

from hypothesis import given, strategies as st

from clarvis.services.weather import calculate_intensity, WEATHER_CODE_INTENSITY
from clarvis.widget.pipeline import Layer


class TestIntensityProperties:
    """Property tests for weather intensity calculation."""

    @given(
        weather_code=st.sampled_from(list(WEATHER_CODE_INTENSITY.keys())),
        wind_speed=st.floats(min_value=0, max_value=200, allow_nan=False),
        precipitation=st.floats(min_value=0, max_value=100, allow_nan=False),
        snowfall=st.floats(min_value=0, max_value=50, allow_nan=False),
    )
    def test_intensity_always_valid(self, weather_code, wind_speed, precipitation, snowfall):
        """Intensity should always be a float between 0 and 1."""
        intensity = calculate_intensity(weather_code, wind_speed, precipitation, snowfall)
        assert isinstance(intensity, float)
        assert 0 <= intensity <= 1


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
        layer.put(x, y, "X")  # Should not raise

    @given(
        width=st.integers(min_value=1, max_value=50),
        height=st.integers(min_value=1, max_value=50),
    )
    def test_layer_clear_resets_all(self, width, height):
        """Clear should reset all cells to spaces."""
        layer = Layer("test", priority=0, width=width, height=height)
        layer.put(0, 0, "A")
        layer.clear()
        assert (layer.chars == 32).all()
