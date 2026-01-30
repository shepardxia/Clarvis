"""Manages periodic data refresh (weather, location, time)."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Optional

from . import get_current_time, write_hub_section, DEFAULT_TIMEZONE

if TYPE_CHECKING:
    from .state import StateStore
    from .display_manager import DisplayManager


class RefreshManager:
    """Manages periodic refresh of weather, location, and time data."""

    def __init__(
        self,
        state: StateStore,
        display_manager: DisplayManager,
        interval: int = 30,
    ):
        self.state = state
        self.display = display_manager
        self.interval = interval

        self._running = False
        self._thread: Optional[threading.Thread] = None

    def refresh_location(self) -> tuple[float, float, str]:
        """Refresh location data."""
        from ..services import get_location
        lat, lon, city = get_location()
        self.state.update("location", {
            "latitude": lat,
            "longitude": lon,
            "city": city,
        })
        return lat, lon, city

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
        write_hub_section("weather", weather_dict)  # Legacy file write
        self.display.set_weather(widget_type, widget_intensity, weather.wind_speed)

        return weather_dict

    def refresh_time(self, timezone: str = None) -> dict:
        """Refresh time data."""
        if timezone is None:
            from ..services import get_cached_timezone
            timezone = get_cached_timezone() or DEFAULT_TIMEZONE

        time_data = get_current_time(timezone)
        time_dict = time_data.to_dict()

        self.state.update("time", time_dict)
        write_hub_section("time", time_dict)  # Legacy file write

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

    def _loop(self) -> None:
        """Background refresh loop."""
        last_refresh = 0

        while self._running:
            current_time = time.time()

            if current_time - last_refresh >= self.interval:
                self.refresh_all()
                last_refresh = current_time

            time.sleep(1)

    def start(self) -> None:
        """Start the background refresh loop."""
        if self._thread is not None and self._thread.is_alive():
            return

        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=False)
        self._thread.start()

    def stop(self) -> None:
        """Stop the background refresh loop."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
