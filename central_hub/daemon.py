#!/usr/bin/env python3
"""Background daemon for Central Hub - handles status processing and data refreshes."""

import json
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from .core import get_hub_section, write_hub_section, get_current_time, read_hub_data, DEFAULT_TIMEZONE
from .services import get_location, get_cached_timezone, fetch_weather
from .widget.renderer import FrameRenderer


class StatusHandler(FileSystemEventHandler):
    """File system event handler for status updates."""

    def __init__(self, daemon):
        self.daemon = daemon
        # Resolve symlinks (e.g., /tmp -> /private/tmp on macOS)
        self._target = str(self.daemon.status_raw_file.resolve())

    def on_modified(self, event):
        if event.src_path == self._target:
            self.daemon.process_status_updates()

    def on_moved(self, event):
        # Atomic writes via mv/rename trigger on_moved, not on_modified
        if event.dest_path == self._target:
            self.daemon.process_status_updates()

    def on_created(self, event):
        if event.src_path == self._target:
            self.daemon.process_status_updates()


class CentralHubDaemon:
    """Background daemon for Central Hub - handles status processing and data refreshes."""
    
    def __init__(
        self,
        status_raw_file: Path = None,
        hub_data_file: Path = None,
        output_file: Path = None,
        refresh_interval: int = 30,
        display_fps: int = 2
    ):
        """Initialize the daemon.
        
        Args:
            status_raw_file: Path to raw status file (default: /tmp/claude-status-raw.json)
            hub_data_file: Path to hub data file (default: /tmp/central-hub-data.json)
            output_file: Path to widget output file (default: /tmp/widget-display.json)
            refresh_interval: Interval in seconds for automatic refresh (default: 30)
            display_fps: Frames per second for display rendering (default: 2)
        """
        self.status_raw_file = status_raw_file or Path("/tmp/claude-status-raw.json")
        self.hub_data_file = hub_data_file or Path("/tmp/central-hub-data.json")
        self.output_file = output_file or Path("/tmp/widget-display.json")
        self.refresh_interval = refresh_interval
        self.display_fps = display_fps
        
        # State variables
        self.observer: Observer | None = None
        self.running = False
        self.background_thread: threading.Thread | None = None
        self.display_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        
        # Stored data
        self.location: dict | None = None
        self.weather: dict | None = None
        self.time: dict | None = None
        self.status: dict | None = None
        
        # Display state
        self.renderer = FrameRenderer()
        self.display_status = "idle"
        self.display_color = "gray"
        self.display_context_percent = 0.0
        self.weather_type = "clear"
        self.weather_intensity = 0.0
        
        # Border styles by status
        self.border_styles = {
            "running": {"width": 3, "pulse": True},
            "thinking": {"width": 3, "pulse": True},
            "awaiting": {"width": 2, "pulse": True},
            "resting": {"width": 1, "pulse": False},
            "idle": {"width": 1, "pulse": False},
            "offline": {"width": 1, "pulse": False},
        }
    
    def process_hook_event(self, raw_data: dict) -> dict:
        """Process raw hook event into status/color."""
        event = raw_data.get("hook_event_name", "")
        context_window = raw_data.get("context_window", {})
        context_percent = context_window.get("used_percentage", 0)

        # Map events to status/color
        if event == "PreToolUse":
            status, color = "running", "green"
        elif event == "PostToolUse":
            status, color = "thinking", "yellow"
        elif event == "UserPromptSubmit":
            status, color = "thinking", "yellow"
        elif event == "Stop":
            status, color = "awaiting", "blue"
        elif event == "Notification":
            status, color = "awaiting", "blue"
        elif context_window:
            # Statusline update - keep existing status but update context
            existing = read_hub_data().get("status", {})
            status = existing.get("status", "idle")
            color = existing.get("color", "gray")
        else:
            status, color = "idle", "gray"

        return {
            "status": status,
            "color": color,
            "context_percent": context_percent,
            "timestamp": datetime.now().isoformat(),
        }
    
    def process_status_updates(self):
        """Watch for raw hook events and process them."""
        if not self.status_raw_file.exists():
            return

        try:
            raw_data = json.loads(self.status_raw_file.read_text())
            processed = self.process_hook_event(raw_data)

            # Read existing hub data and update status
            hub_data = read_hub_data()
            hub_data["status"] = processed
            hub_data["updated_at"] = datetime.now().isoformat()

            # Store in instance
            with self._lock:
                self.status = processed
                self._update_display_from_data()

            # Write atomically
            temp_file = self.hub_data_file.with_suffix('.tmp')
            temp_file.write_text(json.dumps(hub_data, indent=2))
            temp_file.rename(self.hub_data_file)
        except (json.JSONDecodeError, IOError):
            pass
    
    def start_status_watcher(self):
        """Start watching for status updates in background."""
        with self._lock:
            if self.observer is not None:
                return

            # Start file watcher
            self.observer = Observer()
            handler = StatusHandler(self)
            self.observer.schedule(handler, str(self.status_raw_file.parent), recursive=False)
            self.observer.start()

        # Initial processing (outside lock to avoid deadlock)
        self.process_status_updates()
    
    def stop_status_watcher(self):
        """Stop the status watcher."""
        with self._lock:
            if self.observer is not None:
                self.observer.stop()
                self.observer.join()
                self.observer = None
    
    def refresh_location(self) -> tuple[float, float, str]:
        """
        Refresh location data and write to hub.
        
        Returns:
            Tuple of (latitude, longitude, city)
        """
        lat, lon, city = get_location()
        
        # Store in instance
        with self._lock:
            self.location = {
                "latitude": lat,
                "longitude": lon,
                "city": city,
            }
        
        return lat, lon, city
    
    def refresh_weather(self, latitude: float = None, longitude: float = None, city: str = None) -> dict:
        """
        Refresh weather data and write to hub.
        
        Args:
            latitude: Latitude (default: auto-detect)
            longitude: Longitude (default: auto-detect)
            city: City name (default: auto-detect)
        
        Returns:
            Weather data dict
        """
        # Get location if not provided
        if latitude is None or longitude is None:
            latitude, longitude, city = get_location()
        
        # Fetch weather
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

        write_hub_section("weather", weather_dict)
        
        # Store in instance
        with self._lock:
            self.weather = weather_dict
            self._update_weather_display(weather_dict)
        
        return weather_dict
    
    def refresh_time(self, timezone: str = None) -> dict:
        """
        Refresh time data and write to hub.
        
        Args:
            timezone: Timezone name (default: auto-detect from location or use default)
        
        Returns:
            Time data dict
        """
        if timezone is None:
            timezone = get_cached_timezone() or DEFAULT_TIMEZONE
        
        time_data = get_current_time(timezone)
        time_dict = time_data.to_dict()
        write_hub_section("time", time_dict)
        
        # Store in instance
        with self._lock:
            self.time = time_dict
        
        return time_dict
    
    def refresh_all(self):
        """Refresh all data sources."""

        # Get location first (writes to hub data)
        lat, lon, city = self.refresh_location()

        # Fetch weather
        try:
            weather_dict = self.refresh_weather(lat, lon, city)
        except Exception as e:
            pass

        # Update time
        try:
            time_dict = self.refresh_time()
        except Exception as e:
            pass
        
        # Update display with latest data
        with self._lock:
            self._update_display_from_data()
    
    def _background_loop(self):
        """Main background loop - handles periodic refreshes."""
        last_refresh = 0
        
        while self.running:
            current_time = time.time()
            
            # Check if it's time to refresh
            if current_time - last_refresh >= self.refresh_interval:
                self.refresh_all()
                last_refresh = current_time
            
            # Sleep for a short interval before checking again
            time.sleep(1)
    
    def _update_display_from_data(self):
        """Update display state from stored data."""
        if self.status:
            self.display_status = self.status.get("status", "idle")
            self.display_color = self.status.get("color", "gray")
            self.display_context_percent = self.status.get("context_percent", 0)
            self.renderer.set_status(self.display_status)
    
    def _map_weather_to_widget(self, weather_dict: dict) -> tuple[str, float]:
        """Map weather data to widget type and intensity."""
        description = weather_dict.get("description", "").lower()
        wind_speed = weather_dict.get("wind_speed", 0)
        # Use API-calculated intensity (based on weather code, wind, precipitation, snowfall)
        intensity = weather_dict.get("intensity", 0.5)

        # Map description to weather type (for particle sprites)
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

        # Check wind speed - windy overrides clear/cloudy (but not precipitation)
        # 15+ mph = breezy, 25+ mph = windy
        if weather_type in ("clear", "cloudy") and wind_speed >= 15:
            weather_type = "windy"

        return weather_type, intensity

    def _update_weather_display(self, weather_dict: dict):
        """Update weather display from weather data."""
        weather_type, intensity = self._map_weather_to_widget(weather_dict)

        if weather_type != self.weather_type or intensity != self.weather_intensity:
            self.weather_type = weather_type
            self.weather_intensity = intensity
            self.renderer.set_weather(weather_type, intensity)
    
    def _render_display_frame(self):
        """Render and write a display frame."""
        with self._lock:
            frame = self.renderer.render(self.display_context_percent)
            border = self.border_styles.get(self.display_status, {"width": 1, "pulse": False})
            
            output = {
                "frame": frame,
                "color": self.display_color,
                "status": self.display_status,
                "border_width": border["width"],
                "border_pulse": border["pulse"],
                "context_percent": self.display_context_percent,
                "timestamp": time.time(),
            }
        
        # Atomic write
        temp_file = self.output_file.with_suffix(".tmp")
        temp_file.write_text(json.dumps(output))
        temp_file.rename(self.output_file)
    
    def _display_loop(self):
        """Display rendering loop - runs in separate thread."""
        interval = 1.0 / self.display_fps
        
        while self.running:
            start = time.time()
            
            # Advance animation
            with self._lock:
                self.renderer.tick()
            
            # Render and write frame
            self._render_display_frame()
            
            # Sleep to maintain FPS
            elapsed = time.time() - start
            sleep_time = max(0, interval - elapsed)
            time.sleep(sleep_time)
    
    def start_display(self):
        """Start the display rendering thread."""
        if self.display_thread is not None and self.display_thread.is_alive():
            return
        
        self.display_thread = threading.Thread(target=self._display_loop, daemon=True)
        self.display_thread.start()
    
    def stop_display(self):
        """Stop the display rendering thread."""
        # Thread will stop when self.running becomes False
        if self.display_thread is not None:
            self.display_thread.join(timeout=1.0)
            self.display_thread = None
    
    def start(self):
        """Start the daemon (status watcher and periodic refresh)."""
        if self.running:
            return
        
        self.running = True
        
        # Load existing data from hub file
        hub_data = read_hub_data()
        with self._lock:
            self.location = hub_data.get("location")
            self.weather = hub_data.get("weather")
            self.time = hub_data.get("time")
            self.status = hub_data.get("status")
            
            # Initialize display from loaded data
            if self.status:
                self._update_display_from_data()
            if self.weather:
                self._update_weather_display(self.weather)
        
        # Start status watcher
        self.start_status_watcher()
        
        # Start display rendering (writes to JSON file)
        self.start_display()

        # Start background loop for periodic refreshes
        self.start_background_loop()
        
        # Do initial refresh
        self.refresh_all()
    
    def start_background_loop(self):
        """Start the background refresh loop thread."""
        if self.background_thread is not None and self.background_thread.is_alive():
            return
        
        self.background_thread = threading.Thread(target=self._background_loop, daemon=False)
        self.background_thread.start()
    
    def stop_background_loop(self):
        """Stop the background refresh loop thread."""
        # Thread will stop when self.running becomes False
        if self.background_thread is not None:
            self.background_thread.join(timeout=2.0)
            self.background_thread = None
    
    def stop(self):
        """Stop the daemon."""
        if not self.running:
            return
        
        self.running = False
        
        # Stop background loop
        self.stop_background_loop()
        
        # Stop status watcher
        self.stop_status_watcher()
        
        # Stop display rendering
        self.stop_display()
    
    def run(self):
        """Run the daemon until interrupted."""
        self.start()
        try:
            # Keep main thread alive - all work happens in background threads
            while self.running:
                # Check if threads are still alive
                if self.background_thread and not self.background_thread.is_alive():
                    # Restart if it died
                    self.start_background_loop()
                if self.display_thread and not self.display_thread.is_alive():
                    # Restart if it died
                    self.start_display()
                
                time.sleep(5)  # Check every 5 seconds
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()


# Global daemon instance for backward compatibility
_daemon_instance: CentralHubDaemon | None = None


def get_daemon() -> CentralHubDaemon:
    """Get or create the global daemon instance."""
    global _daemon_instance
    if _daemon_instance is None:
        _daemon_instance = CentralHubDaemon()
    return _daemon_instance


# Backward compatibility functions
def refresh_location() -> tuple[float, float, str]:
    """Refresh location data and write to hub."""
    return get_daemon().refresh_location()


def refresh_weather(latitude: float = None, longitude: float = None, city: str = None) -> dict:
    """Refresh weather data and write to hub."""
    return get_daemon().refresh_weather(latitude, longitude, city)


def refresh_time(timezone: str = None) -> dict:
    """Refresh time data and write to hub."""
    return get_daemon().refresh_time(timezone)


def refresh_all():
    """Refresh all data sources."""
    get_daemon().refresh_all()


def main():
    """Entry point for daemon mode."""
    if len(sys.argv) > 1 and sys.argv[1] == "--refresh":
        # One-time refresh of all data sources
        daemon = CentralHubDaemon()
        daemon.refresh_all()
    else:
        # Run as daemon
        daemon = CentralHubDaemon()
        daemon.run()


if __name__ == "__main__":
    main()

