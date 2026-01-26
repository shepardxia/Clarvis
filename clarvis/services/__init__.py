"""External services - location, weather, thinking feed, whimsy verbs."""

from .location import get_location, get_cached_timezone
from .weather import fetch_weather, WeatherData
from .thinking_feed import get_session_manager, SessionManager
from .whimsy_verb import generate_whimsy_verb

__all__ = [
    "get_location",
    "get_cached_timezone",
    "fetch_weather",
    "WeatherData",
    "get_session_manager",
    "SessionManager",
    "generate_whimsy_verb",
]
