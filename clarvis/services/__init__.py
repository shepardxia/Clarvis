"""External services - weather/location, thinking feed, activity monitoring, memory."""

from .thinking_feed import SessionManager, get_session_manager
from .weather import WeatherData, fetch_weather, get_location

__all__ = [
    "get_location",
    "fetch_weather",
    "WeatherData",
    "get_session_manager",
    "SessionManager",
]
