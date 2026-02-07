"""Weather and location services via Open-Meteo API and geolocation."""

from __future__ import annotations

import json
import subprocess
import time as _time
from dataclasses import dataclass

import requests

# --- Location detection ---

CORELOCATION_CMD = "CoreLocationCLI"
_corelocation_available: bool | None = None

_cache: dict | None = None
_cache_time: float = 0.0

DEFAULT_LOCATION = {
    "latitude": 37.7749,
    "longitude": -122.4194,
    "city": "San Francisco",
    "timezone": "",
    "source": "default",
}


def _is_corelocation_available() -> bool:
    global _corelocation_available
    if _corelocation_available is not None:
        return _corelocation_available
    try:
        result = subprocess.run(["which", CORELOCATION_CMD], capture_output=True, timeout=2)
        _corelocation_available = result.returncode == 0
    except (subprocess.TimeoutExpired, Exception):
        _corelocation_available = False
    return _corelocation_available


def _get_location_corelocation() -> dict | None:
    """Try to get location via macOS CoreLocation (more accurate, OPTIONAL)."""
    if not _is_corelocation_available():
        return None
    try:
        result = subprocess.run([CORELOCATION_CMD, "-j"], capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return {
                "latitude": float(data["latitude"]),
                "longitude": float(data["longitude"]),
                "city": data.get("locality", ""),
                "region": data.get("administrativeArea", ""),
                "country": data.get("country", ""),
                "timezone": data.get("timeZone", ""),
                "source": "corelocation",
            }
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError, Exception):
        pass
    return None


def _get_location_ip() -> dict | None:
    """Get location via IP geolocation (fallback)."""
    try:
        response = requests.get("http://ip-api.com/json/", timeout=5)
        response.raise_for_status()
        data = response.json()
        if data.get("status") == "success":
            return {
                "latitude": data["lat"],
                "longitude": data["lon"],
                "city": data.get("city", "Unknown"),
                "region": data.get("regionName", ""),
                "country": data.get("country", ""),
                "timezone": data.get("timezone", ""),
                "source": "ip",
            }
    except requests.RequestException:
        pass
    return None


def get_location_full(cache_max_age: int = 60) -> dict:
    """Get full location dict with automatic fallback.

    Tries: CoreLocation cache → CoreLocation → IP cache → IP API → default.
    """
    global _cache, _cache_time

    cached = _cache if _cache and (_time.time() - _cache_time) < cache_max_age else None

    if cached and cached.get("source") == "corelocation":
        return cached

    location_data = _get_location_corelocation()
    if location_data:
        _cache = location_data
        _cache_time = _time.time()
        return location_data

    if cached:
        return cached

    location_data = _get_location_ip()
    if location_data:
        _cache = location_data
        _cache_time = _time.time()
        return location_data

    return DEFAULT_LOCATION


def get_location(cache_max_age: int = 60) -> tuple[float, float, str]:
    """Get current location as (latitude, longitude, city) tuple."""
    loc = get_location_full(cache_max_age)
    return loc["latitude"], loc["longitude"], loc["city"]


# --- Weather ---

# WMO Weather interpretation codes
# https://open-meteo.com/en/docs
WEATHER_CODES = {
    0: "Clear",
    1: "Mostly Clear",
    2: "Partly Cloudy",
    3: "Overcast",
    45: "Foggy",
    48: "Icy Fog",
    51: "Light Drizzle",
    53: "Drizzle",
    55: "Heavy Drizzle",
    61: "Light Rain",
    63: "Rain",
    65: "Heavy Rain",
    71: "Light Snow",
    73: "Snow",
    75: "Heavy Snow",
    80: "Light Showers",
    81: "Showers",
    82: "Heavy Showers",
    95: "Thunderstorm",
}

# Base intensity by weather code (0-1 scale)
# More severe weather = higher base intensity
WEATHER_CODE_INTENSITY = {
    0: 0.0,  # Clear
    1: 0.0,  # Mostly Clear
    2: 0.0,  # Partly Cloudy
    3: 0.1,  # Overcast
    45: 0.2,  # Foggy
    48: 0.3,  # Icy Fog
    51: 0.3,  # Light Drizzle
    53: 0.4,  # Drizzle
    55: 0.5,  # Heavy Drizzle
    61: 0.4,  # Light Rain
    63: 0.6,  # Rain
    65: 0.8,  # Heavy Rain
    71: 0.4,  # Light Snow
    73: 0.6,  # Snow
    75: 0.8,  # Heavy Snow
    80: 0.5,  # Light Showers
    81: 0.7,  # Showers
    82: 0.9,  # Heavy Showers
    95: 1.0,  # Thunderstorm
}


@dataclass
class WeatherData:
    """Weather data from Open-Meteo API."""

    temperature: float
    weather_code: int
    wind_speed: float
    description: str
    precipitation: float  # mm
    snowfall: float  # cm
    intensity: float  # 0-1 calculated intensity

    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        return {
            "temperature": self.temperature,
            "weather_code": self.weather_code,
            "wind_speed": self.wind_speed,
            "description": self.description,
            "precipitation": self.precipitation,
            "snowfall": self.snowfall,
            "intensity": self.intensity,
        }


def weather_code_to_desc(code: int) -> str:
    """Convert WMO weather code to human-readable description."""
    return WEATHER_CODES.get(code, "Unknown")


def calculate_intensity(
    weather_code: int,
    wind_speed: float,
    precipitation: float,
    snowfall: float,
) -> float:
    """
    Calculate weather intensity on 0-1 scale.

    Combines:
    - Base intensity from weather code (40% weight)
    - Wind speed contribution (20% weight) - 0-50 mph mapped to 0-1
    - Precipitation contribution (20% weight) - 0-10mm mapped to 0-1
    - Snowfall contribution (20% weight) - 0-5cm mapped to 0-1

    Returns:
        Float 0-1, higher = more intense weather
    """
    # Base intensity from weather code
    base = WEATHER_CODE_INTENSITY.get(weather_code, 0.0)

    # Wind contribution: 0-50 mph -> 0-1 (capped)
    wind_factor = min(wind_speed / 50.0, 1.0)

    # Precipitation contribution: 0-10mm -> 0-1 (capped)
    precip_factor = min(precipitation / 10.0, 1.0)

    # Snowfall contribution: 0-5cm -> 0-1 (capped)
    snow_factor = min(snowfall / 5.0, 1.0)

    # Weighted combination
    intensity = base * 0.4 + wind_factor * 0.2 + precip_factor * 0.2 + snow_factor * 0.2

    # Clamp to 0-1
    return min(max(intensity, 0.0), 1.0)


def fetch_weather(latitude: float, longitude: float) -> WeatherData:
    """
    Fetch current weather from Open-Meteo API.

    Args:
        latitude: Location latitude
        longitude: Location longitude

    Returns:
        WeatherData with current conditions

    Raises:
        requests.RequestException: On network/API errors
    """
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={latitude}&longitude={longitude}"
        f"&current=temperature_2m,weather_code,wind_speed_10m,precipitation,snowfall"
        f"&temperature_unit=fahrenheit"
        f"&wind_speed_unit=mph"
    )

    response = requests.get(url, timeout=10)
    response.raise_for_status()
    data = response.json()

    current = data.get("current", {})
    weather_code = current.get("weather_code", 0)
    wind_speed = current.get("wind_speed_10m", 0)
    precipitation = current.get("precipitation", 0)
    snowfall = current.get("snowfall", 0)

    intensity = calculate_intensity(weather_code, wind_speed, precipitation, snowfall)

    return WeatherData(
        temperature=current.get("temperature_2m", 0),
        weather_code=weather_code,
        wind_speed=wind_speed,
        description=weather_code_to_desc(weather_code),
        precipitation=precipitation,
        snowfall=snowfall,
        intensity=intensity,
    )
