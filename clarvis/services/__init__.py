"""External services - weather, timers, session tracking, memory maintenance."""

from .weather import WeatherData, fetch_weather, get_location

__all__ = [
    "get_location",
    "fetch_weather",
    "WeatherData",
]
