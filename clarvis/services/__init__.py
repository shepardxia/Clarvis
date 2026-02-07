"""External services - weather/location, thinking feed, whimsy verbs."""

from .thinking_feed import SessionManager, get_session_manager
from .weather import WeatherData, fetch_weather, get_location
from .whimsy_verb import generate_whimsy_verb

__all__ = [
    "get_location",
    "fetch_weather",
    "WeatherData",
    "get_session_manager",
    "SessionManager",
    "generate_whimsy_verb",
]
