"""Tests for weather service."""

import pytest
import responses
from responses import matchers

from central_hub.services.weather import (
    fetch_weather,
    calculate_intensity,
    weather_code_to_desc,
    WEATHER_CODES,
    WEATHER_CODE_INTENSITY,
)


class TestWeatherCodeToDesc:
    """Tests for weather code description mapping."""

    def test_clear(self):
        assert weather_code_to_desc(0) == "Clear"

    def test_rain(self):
        assert weather_code_to_desc(63) == "Rain"

    def test_heavy_snow(self):
        assert weather_code_to_desc(75) == "Heavy Snow"

    def test_thunderstorm(self):
        assert weather_code_to_desc(95) == "Thunderstorm"

    def test_unknown_code(self):
        assert weather_code_to_desc(999) == "Unknown"


class TestCalculateIntensity:
    """Tests for weather intensity calculation."""

    def test_clear_calm_low_intensity(self):
        """Clear weather with no wind should have very low intensity."""
        intensity = calculate_intensity(
            weather_code=0, wind_speed=5, precipitation=0, snowfall=0
        )
        assert 0 <= intensity <= 0.1

    def test_thunderstorm_high_intensity(self):
        """Thunderstorm should have high intensity."""
        intensity = calculate_intensity(
            weather_code=95, wind_speed=30, precipitation=10, snowfall=0
        )
        assert intensity >= 0.7

    def test_heavy_snow_windy(self):
        """Heavy snow with wind should have high intensity."""
        intensity = calculate_intensity(
            weather_code=75, wind_speed=35, precipitation=0, snowfall=4
        )
        assert intensity >= 0.5

    def test_intensity_always_in_range(self):
        """Intensity should always be between 0 and 1."""
        # Test with extreme values
        test_cases = [
            (0, 0, 0, 0),       # Minimum
            (95, 100, 50, 20),  # Extreme maximum
            (63, 25, 5, 0),     # Moderate rain
        ]
        for code, wind, precip, snow in test_cases:
            intensity = calculate_intensity(code, wind, precip, snow)
            assert 0 <= intensity <= 1, f"Failed for {code}, {wind}, {precip}, {snow}"

    def test_wind_increases_intensity(self):
        """Higher wind should increase intensity."""
        low_wind = calculate_intensity(0, 5, 0, 0)
        high_wind = calculate_intensity(0, 40, 0, 0)
        assert high_wind > low_wind

    def test_precipitation_increases_intensity(self):
        """Higher precipitation should increase intensity."""
        no_precip = calculate_intensity(61, 10, 0, 0)
        high_precip = calculate_intensity(61, 10, 8, 0)
        assert high_precip > no_precip


class TestFetchWeather:
    """Tests for fetch_weather with mocked API."""

    @responses.activate
    def test_fetch_weather_success(self, mock_weather_response):
        """Test successful weather fetch."""
        responses.add(
            responses.GET,
            "https://api.open-meteo.com/v1/forecast",
            json=mock_weather_response,
            status=200,
        )

        weather = fetch_weather(37.7749, -122.4194)

        assert weather.temperature == 65.0
        assert weather.weather_code == 3
        assert weather.wind_speed == 12.5
        assert weather.description == "Overcast"
        assert 0 <= weather.intensity <= 1

    @responses.activate
    def test_fetch_weather_rain(self, mock_weather_response_rain):
        """Test weather fetch for rainy conditions."""
        responses.add(
            responses.GET,
            "https://api.open-meteo.com/v1/forecast",
            json=mock_weather_response_rain,
            status=200,
        )

        weather = fetch_weather(37.7749, -122.4194)

        assert weather.description == "Rain"
        assert weather.precipitation == 5.5
        assert weather.intensity > 0.3  # Rain should have noticeable intensity

    @responses.activate
    def test_fetch_weather_snow(self, mock_weather_response_snow):
        """Test weather fetch for snowy conditions."""
        responses.add(
            responses.GET,
            "https://api.open-meteo.com/v1/forecast",
            json=mock_weather_response_snow,
            status=200,
        )

        weather = fetch_weather(37.7749, -122.4194)

        assert weather.description == "Heavy Snow"
        assert weather.snowfall == 3.5
        assert weather.intensity > 0.5  # Heavy snow should have high intensity

    @responses.activate
    def test_fetch_weather_api_error(self):
        """Test handling of API errors."""
        responses.add(
            responses.GET,
            "https://api.open-meteo.com/v1/forecast",
            status=500,
        )

        with pytest.raises(Exception):
            fetch_weather(37.7749, -122.4194)
