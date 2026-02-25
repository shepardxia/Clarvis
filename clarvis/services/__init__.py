"""External services - weather/location, activity monitoring, memory."""

from .weather import WeatherData, fetch_weather, get_location

__all__ = [
    "get_location",
    "fetch_weather",
    "WeatherData",
]
