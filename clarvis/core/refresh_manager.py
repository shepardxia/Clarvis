"""Manages data refresh (weather, location, time).

Business logic only — scheduling is handled by the Scheduler.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import get_current_time, DEFAULT_TIMEZONE

if TYPE_CHECKING:
    from .state import StateStore
    from .display_manager import DisplayManager


class RefreshManager:
    """Refreshes weather, location, and time data.

    This is a passive service — it exposes refresh methods but does not
    run its own thread.  The daemon's Scheduler calls ``refresh_all()``
    periodically.
    """

    def __init__(
        self,
        state: StateStore,
        display_manager: DisplayManager,
    ):
        self.state = state
        self.display = display_manager

    def refresh_location(self) -> tuple[float, float, str]:
        """Refresh location data."""
        from ..services.location import get_location_full
        location_data = get_location_full()
        self.state.update("location", location_data)
        return location_data["latitude"], location_data["longitude"], location_data["city"]

    def refresh_weather(
        self,
        latitude: float = None,
        longitude: float = None,
        city: str = None,
    ) -> dict:
        """Refresh weather data."""
        if latitude is None or longitude is None:
            from ..services import get_location
            latitude, longitude, city = get_location()

        from ..services import fetch_weather
        weather = fetch_weather(latitude, longitude)
        weather_dict = {
            **weather.to_dict(),
            "latitude": latitude,
            "longitude": longitude,
            "city": city or "Unknown",
        }

        # Add widget-mapped weather type and intensity
        widget_type, widget_intensity = self._map_weather_to_widget(weather_dict)
        weather_dict["widget_type"] = widget_type
        weather_dict["widget_intensity"] = widget_intensity

        # Update state and display
        self.state.update("weather", weather_dict)
        self.display.set_weather(widget_type, widget_intensity, weather.wind_speed)

        return weather_dict

    def refresh_time(self, timezone: str = None) -> dict:
        """Refresh time data."""
        if timezone is None:
            location = self.state.get("location")
            timezone = location.get("timezone") if location else None
            timezone = timezone or DEFAULT_TIMEZONE

        time_data = get_current_time(timezone)
        time_dict = time_data.to_dict()

        self.state.update("time", time_dict)

        return time_dict

    def refresh_all(self) -> None:
        """Refresh all data sources."""
        lat, lon, city = self.refresh_location()

        try:
            self.refresh_weather(lat, lon, city)
        except Exception:
            pass

        try:
            self.refresh_time()
        except Exception:
            pass

    def _map_weather_to_widget(self, weather_dict: dict) -> tuple[str, float]:
        """Map weather data to widget type and intensity."""
        description = weather_dict.get("description", "").lower()
        wind_speed = weather_dict.get("wind_speed", 0)
        intensity = weather_dict.get("intensity", 0.5)

        weather_type = "clear"

        if "snow" in description:
            weather_type = "snow"
        elif "rain" in description or "shower" in description or "drizzle" in description:
            weather_type = "rain"
        elif "thunder" in description:
            weather_type = "rain"
        elif "fog" in description:
            weather_type = "fog"
        elif "cloud" in description or "overcast" in description:
            weather_type = "cloudy"

        if weather_type in ("clear", "cloudy") and wind_speed >= 15:
            weather_type = "windy"

        return weather_type, intensity
