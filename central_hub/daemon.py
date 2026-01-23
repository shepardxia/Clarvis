#!/usr/bin/env python3
"""Background daemon for Central Hub - handles status processing and data refreshes."""

from __future__ import annotations

import json
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from .core import get_hub_section, write_hub_section, get_current_time, read_hub_data, DEFAULT_TIMEZONE
from .core.state import StateStore, get_state_store
from .core.ipc import DaemonServer
from .services import get_location, get_cached_timezone, fetch_weather
from .services.token_usage import TokenUsageService
from .widget.renderer import FrameRenderer
from .widget.config import get_config, watch_config, WidgetConfig, restart_daemon_and_widget
from .widget.socket_server import WidgetSocketServer, get_socket_server


class StatusHandler(FileSystemEventHandler):
    """File system event handler for status updates."""

    def __init__(self, daemon):
        self.daemon = daemon
        self._target = str(self.daemon.status_raw_file.resolve())

    def on_modified(self, event):
        if event.src_path == self._target:
            self.daemon.process_status_updates()

    def on_moved(self, event):
        if event.dest_path == self._target:
            self.daemon.process_status_updates()

    def on_created(self, event):
        if event.src_path == self._target:
            self.daemon.process_status_updates()


class CentralHubDaemon:
    """Background daemon for Central Hub - uses StateStore as single source of truth."""

    # Configuration
    HISTORY_SIZE = 20
    SESSION_TIMEOUT = 300  # 5 minutes

    def __init__(
        self,
        status_raw_file: Path = None,
        hub_data_file: Path = None,
        output_file: Path = None,
        refresh_interval: int = 30,
        display_fps: int = 2,
        state_store: StateStore = None,
        socket_server: WidgetSocketServer = None,
    ):
        # File paths
        self.status_raw_file = status_raw_file or Path("/tmp/claude-status-raw.json")
        self.hub_data_file = hub_data_file or Path("/tmp/central-hub-data.json")
        self.output_file = output_file or Path("/tmp/widget-display.json")
        self.refresh_interval = refresh_interval
        self.display_fps = display_fps

        # Core components - single source of truth
        self.state = state_store or get_state_store()
        self.socket_server = socket_server or get_socket_server()
        self.command_server = DaemonServer()
        self.token_usage_service: Optional[TokenUsageService] = None

        # Threading
        self.observer: Observer | None = None
        self.running = False
        self.background_thread: threading.Thread | None = None
        self.display_thread: threading.Thread | None = None
        self._lock = threading.Lock()

        # Display rendering
        config = get_config()
        self.renderer = FrameRenderer(
            width=config.grid_width,
            height=config.grid_height,
            avatar_x_offset=config.display.avatar_x_offset,
            avatar_y_offset=config.display.avatar_y_offset,
            bar_x_offset=config.display.bar_x_offset,
            bar_y_offset=config.display.bar_y_offset,
        )
        self.displayed_session_id: str | None = None

        # Border styles by status
        self.border_styles = {
            "running": {"width": 3, "pulse": True},
            "thinking": {"width": 3, "pulse": True},
            "awaiting": {"width": 2, "pulse": True},
            "resting": {"width": 1, "pulse": False},
            "idle": {"width": 1, "pulse": False},
            "offline": {"width": 1, "pulse": False},
        }

        # Load initial state from hub file
        self._load_initial_state()

        # Subscribe to state changes for file persistence
        self.state.subscribe(self._on_state_change)

    # --- Backward-compatible properties ---

    @property
    def sessions(self) -> dict:
        """Backward-compatible access to sessions."""
        return self.state.get("sessions")

    @property
    def display_status(self) -> str:
        """Backward-compatible access to display status."""
        status = self.state.get("status")
        return status.get("status", "idle") if status else "idle"

    @property
    def display_color(self) -> str:
        """Backward-compatible access to display color."""
        status = self.state.get("status")
        return status.get("color", "gray") if status else "gray"

    @property
    def display_context_percent(self) -> float:
        """Backward-compatible access to display context percent."""
        status = self.state.get("status")
        return status.get("context_percent", 0.0) if status else 0.0

    def _load_initial_state(self):
        """Load initial state from hub data file."""
        hub_data = read_hub_data()

        # Load into StateStore
        if hub_data.get("status"):
            self.state.update("status", hub_data["status"], notify=False)
        if hub_data.get("sessions"):
            self.state.update("sessions", hub_data["sessions"], notify=False)
        if hub_data.get("weather"):
            self.state.update("weather", hub_data["weather"], notify=False)
        if hub_data.get("location"):
            self.state.update("location", hub_data["location"], notify=False)
        if hub_data.get("time"):
            self.state.update("time", hub_data["time"], notify=False)

        # Initialize renderer from loaded state
        status = self.state.get("status")
        if status:
            self.renderer.set_status(status.get("status", "idle"))

        weather = self.state.get("weather")
        if weather:
            weather_type = weather.get("widget_type", "clear")
            intensity = weather.get("widget_intensity", 0.0)
            wind_speed = weather.get("wind_speed", 0.0)
            self.renderer.set_weather(weather_type, intensity, wind_speed)

    def _on_state_change(self, section: str, value: dict):
        """Handle state changes - persist to file."""
        self._persist_to_file()

    def _persist_to_file(self):
        """Persist current state to hub data file."""
        hub_data = self.state.get_all()
        hub_data["updated_at"] = datetime.now().isoformat()

        temp_file = self.hub_data_file.with_suffix('.tmp')
        temp_file.write_text(json.dumps(hub_data, indent=2))
        temp_file.rename(self.hub_data_file)

    # --- Session Management ---

    def _get_session(self, session_id: str) -> dict:
        """Get or create session tracking data."""
        sessions = self.state.get("sessions")
        if session_id not in sessions:
            sessions[session_id] = {
                "status_history": [],
                "context_history": [],
                "last_status": "idle",
                "last_context": 0.0,
                "last_seen": time.time(),
            }
            self.state.update("sessions", sessions)
        return sessions[session_id]

    def _add_to_history(self, session_id: str, status: str, context_percent: float):
        """Add values to per-session history buffers."""
        sessions = self.state.get("sessions")
        session = sessions.get(session_id) or {
            "status_history": [],
            "context_history": [],
            "last_status": "idle",
            "last_context": 0.0,
        }

        # Update last_seen for session cleanup
        session["last_seen"] = time.time()

        # Set displayed session if none set
        if self.displayed_session_id is None:
            self.displayed_session_id = session_id

        # Only add status if it changed
        history = session.get("status_history", [])
        if not history or history[-1] != status:
            history.append(status)
            if len(history) > self.HISTORY_SIZE:
                history.pop(0)
        session["status_history"] = history
        session["last_status"] = status

        # Only add context if it's a valid non-zero value
        if context_percent > 0:
            ctx_history = session.get("context_history", [])
            ctx_history.append(context_percent)
            if len(ctx_history) > self.HISTORY_SIZE:
                ctx_history.pop(0)
            session["context_history"] = ctx_history
            session["last_context"] = context_percent

        sessions[session_id] = session
        self.state.update("sessions", sessions)

    def _get_last_context(self, session_id: str) -> float:
        """Get last known context percent for session."""
        sessions = self.state.get("sessions")
        session = sessions.get(session_id, {})
        return session.get("last_context", 0.0)

    def _cleanup_stale_sessions(self):
        """Remove sessions inactive for > SESSION_TIMEOUT."""
        now = time.time()
        sessions = self.state.get("sessions")
        active = {
            sid: data for sid, data in sessions.items()
            if now - data.get("last_seen", 0) < self.SESSION_TIMEOUT
        }
        if len(active) != len(sessions):
            self.state.update("sessions", active)
            # Reset displayed session if it was cleaned up
            if self.displayed_session_id not in active:
                self.displayed_session_id = next(iter(active), None)

    # --- Status Processing ---

    def process_hook_event(self, raw_data: dict) -> dict:
        """Process raw hook event into status/color."""
        session_id = raw_data.get("session_id", "unknown")
        event = raw_data.get("hook_event_name", "")
        context_window = raw_data.get("context_window") or {}
        context_percent = context_window.get("used_percentage") or 0

        # Get existing status from state (no file read needed!)
        existing_status = self.state.get("status")

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
            status = existing_status.get("status", "idle")
            color = existing_status.get("color", "gray")
        else:
            status, color = "idle", "gray"

        # Update per-session history
        self._add_to_history(session_id, status, context_percent)

        # Use last known context if current is 0
        effective_context = context_percent if context_percent else self._get_last_context(session_id)

        # Get session data for output
        sessions = self.state.get("sessions")
        session = sessions.get(session_id, {})

        return {
            "session_id": session_id,
            "status": status,
            "color": color,
            "context_percent": effective_context,
            "status_history": session.get("status_history", []).copy(),
            "context_history": session.get("context_history", []).copy(),
            "timestamp": datetime.now().isoformat(),
        }

    def process_status_updates(self):
        """Watch for raw hook events and process them."""
        if not self.status_raw_file.exists():
            return

        try:
            raw_data = json.loads(self.status_raw_file.read_text())
            processed = self.process_hook_event(raw_data)

            # Update state (triggers observers, including file persistence)
            self.state.update("status", processed)

            # Update renderer if this is the displayed session
            if processed.get("session_id") == self.displayed_session_id:
                with self._lock:
                    self.renderer.set_status(processed.get("status", "idle"))

            # Periodically clean up stale sessions
            self._cleanup_stale_sessions()

        except (json.JSONDecodeError, IOError):
            pass

    # --- Status Watcher ---

    def start_status_watcher(self):
        """Start watching for status updates in background."""
        with self._lock:
            if self.observer is not None:
                return

            self.observer = Observer()
            handler = StatusHandler(self)
            self.observer.schedule(handler, str(self.status_raw_file.parent), recursive=False)
            self.observer.start()

        self.process_status_updates()

    def stop_status_watcher(self):
        """Stop the status watcher."""
        with self._lock:
            if self.observer is not None:
                self.observer.stop()
                self.observer.join()
                self.observer = None

    # --- Data Refresh ---

    def refresh_location(self) -> tuple[float, float, str]:
        """Refresh location data."""
        lat, lon, city = get_location()
        self.state.update("location", {
            "latitude": lat,
            "longitude": lon,
            "city": city,
        })
        return lat, lon, city

    def refresh_weather(self, latitude: float = None, longitude: float = None, city: str = None) -> dict:
        """Refresh weather data."""
        if latitude is None or longitude is None:
            latitude, longitude, city = get_location()

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

        # Update state and renderer
        self.state.update("weather", weather_dict)
        write_hub_section("weather", weather_dict)  # Legacy file write

        with self._lock:
            self.renderer.set_weather(widget_type, widget_intensity, weather.wind_speed)

        return weather_dict

    def refresh_time(self, timezone: str = None) -> dict:
        """Refresh time data."""
        if timezone is None:
            timezone = get_cached_timezone() or DEFAULT_TIMEZONE

        time_data = get_current_time(timezone)
        time_dict = time_data.to_dict()

        self.state.update("time", time_dict)
        write_hub_section("time", time_dict)  # Legacy file write

        return time_dict

    def refresh_all(self):
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

    # --- Display Rendering ---

    def _render_display_frame(self):
        """Render and output a display frame."""
        config = get_config()

        with self._lock:
            # In testing mode, use config overrides
            if config.testing.enabled:
                display_status = config.test_status
                context_percent = config.test_context_percent
                display_color = {
                    "idle": "gray", "thinking": "yellow", "running": "green",
                    "awaiting": "blue", "resting": "gray"
                }.get(display_status, "gray")

                # Apply test weather if different from current
                self.renderer.set_status(display_status)
                self.renderer.set_weather(
                    config.test_weather,
                    config.test_weather_intensity,
                    config.test_wind_speed
                )
            else:
                status = self.state.get("status")
                context_percent = status.get("context_percent", 0) if status else 0
                display_status = status.get("status", "idle") if status else "idle"
                display_color = status.get("color", "gray") if status else "gray"

            frame = self.renderer.render(context_percent)
            border = self.border_styles.get(display_status, {"width": 1, "pulse": False})

            output = {
                "frame": frame,
                "color": display_color,
                "status": display_status,
                "border_width": border["width"],
                "border_pulse": border["pulse"],
                "context_percent": context_percent,
                "timestamp": time.time(),
            }

        # Push to socket (new way)
        self.socket_server.push_frame(output)

        # Also write to file (backward compatibility)
        temp_file = self.output_file.with_suffix(".tmp")
        temp_file.write_text(json.dumps(output))
        temp_file.rename(self.output_file)

    def _display_loop(self):
        """Display rendering loop."""
        interval = 1.0 / self.display_fps

        while self.running:
            start = time.time()

            with self._lock:
                self.renderer.tick()

            self._render_display_frame()

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
        if self.display_thread is not None:
            self.display_thread.join(timeout=1.0)
            self.display_thread = None

    # --- Background Loop ---

    def _background_loop(self):
        """Main background loop - handles periodic refreshes."""
        last_refresh = 0

        while self.running:
            current_time = time.time()

            if current_time - last_refresh >= self.refresh_interval:
                self.refresh_all()
                last_refresh = current_time

            time.sleep(1)

    def start_background_loop(self):
        """Start the background refresh loop thread."""
        if self.background_thread is not None and self.background_thread.is_alive():
            return

        self.background_thread = threading.Thread(target=self._background_loop, daemon=False)
        self.background_thread.start()

    def stop_background_loop(self):
        """Stop the background refresh loop thread."""
        if self.background_thread is not None:
            self.background_thread.join(timeout=2.0)
            self.background_thread = None

    # --- Lifecycle ---

    def _on_config_change(self, new_config: WidgetConfig):
        """Handle config file changes."""
        # Check if grid size changed (requires restart)
        if (new_config.grid_width != self.renderer.width or
            new_config.grid_height != self.renderer.height):
            print(f"Grid size changed, restarting...")
            restart_daemon_and_widget()
            return

        # If testing mode, apply overrides immediately
        if new_config.testing.enabled:
            with self._lock:
                self.renderer.set_status(new_config.test_status)
                self.renderer.set_weather(
                    new_config.test_weather,
                    new_config.test_weather_intensity,
                    new_config.test_wind_speed
                )

    def _register_command_handlers(self):
        """Register handlers for IPC commands from MCP server."""
        # State queries
        self.command_server.register("get_state", self._cmd_get_state)
        self.command_server.register("get_status", self._cmd_get_status)
        self.command_server.register("get_weather", self._cmd_get_weather)
        self.command_server.register("get_sessions", self._cmd_get_sessions)
        self.command_server.register("get_session", self._cmd_get_session)
        self.command_server.register("get_token_usage", self.get_token_usage)

        # Actions
        self.command_server.register("refresh_weather", self._cmd_refresh_weather)
        self.command_server.register("refresh_time", self._cmd_refresh_time)
        self.command_server.register("refresh_location", self._cmd_refresh_location)
        self.command_server.register("refresh_all", self._cmd_refresh_all)

        # Utility
        self.command_server.register("ping", lambda: "pong")

    def _cmd_get_state(self) -> dict:
        """Get full Clarvis state."""
        status = self.state.get("status")
        weather = self.state.get("weather")
        time_data = self.state.get("time")
        sessions = self.state.get("sessions")

        session_details = {}
        for session_id, data in sessions.items():
            session_details[session_id] = {
                "last_status": data.get("last_status", "unknown"),
                "last_context": data.get("last_context", 0),
                "status_history": data.get("status_history", []),
                "context_history": data.get("context_history", []),
            }

        return {
            "displayed_session": status.get("session_id"),
            "status": status.get("status", "unknown"),
            "color": status.get("color", "gray"),
            "context_percent": status.get("context_percent", 0),
            "status_history": status.get("status_history", []),
            "context_history": status.get("context_history", []),
            "weather": {
                "type": weather.get("description", "unknown"),
                "temperature": weather.get("temperature"),
                "wind_speed": weather.get("wind_speed", 0),
                "intensity": weather.get("intensity", 0),
                "city": weather.get("city", "unknown"),
                "widget_type": weather.get("widget_type", "clear"),
            },
            "time": time_data.get("timestamp"),
            "sessions": session_details,
        }

    def _cmd_get_status(self) -> dict:
        """Get current status."""
        return self.state.get("status")

    def _cmd_get_weather(self) -> dict:
        """Get current weather."""
        return self.state.get("weather")

    def _cmd_get_sessions(self) -> list:
        """List all tracked sessions."""
        sessions = self.state.get("sessions")
        status = self.state.get("status")
        displayed = status.get("session_id") if status else None

        result = []
        for session_id, data in sessions.items():
            result.append({
                "session_id": session_id,
                "is_displayed": session_id == displayed,
                "last_status": data.get("last_status", "unknown"),
                "last_context": data.get("last_context", 0),
                "status_history_length": len(data.get("status_history", [])),
                "context_history_length": len(data.get("context_history", [])),
            })
        return result

    def _cmd_get_session(self, session_id: str) -> dict:
        """Get details for a specific session."""
        sessions = self.state.get("sessions")
        status = self.state.get("status")
        displayed = status.get("session_id") if status else None

        if session_id not in sessions:
            raise ValueError(f"Session {session_id} not found")

        data = sessions[session_id]
        return {
            "session_id": session_id,
            "is_displayed": session_id == displayed,
            "last_status": data.get("last_status", "unknown"),
            "last_context": data.get("last_context", 0),
            "status_history": data.get("status_history", []),
            "context_history": data.get("context_history", []),
        }

    def get_token_usage(self) -> Dict[str, Any]:
        """Get current token usage data.

        Returns:
            Dict with usage data, last_updated, and is_stale flag
        """
        if not self.token_usage_service:
            return {"error": "Token usage service not initialized", "is_stale": True}
        return self.token_usage_service.get_usage()

    def _cmd_refresh_weather(self, latitude: float = None, longitude: float = None) -> dict:
        """Refresh weather and return new data."""
        return self.refresh_weather(latitude, longitude)

    def _cmd_refresh_time(self, timezone: str = None) -> dict:
        """Refresh time and return new data."""
        return self.refresh_time(timezone)

    def _cmd_refresh_location(self) -> dict:
        """Refresh location and return new data."""
        lat, lon, city = self.refresh_location()
        return {"latitude": lat, "longitude": lon, "city": city}

    def _cmd_refresh_all(self) -> str:
        """Refresh all data sources."""
        self.refresh_all()
        return "ok"

    def start(self):
        """Start the daemon."""
        if self.running:
            return

        self.running = True

        # Start config watcher
        self.config_watcher = watch_config(self._on_config_change)

        # Register and start command server for MCP communication
        self._register_command_handlers()
        self.command_server.start()

        # Start socket server for widget connections
        self.socket_server.start()

        # Initialize token usage service
        # TODO: In Task 4 (config structure), read poll_interval from config.token_usage.poll_interval
        self.token_usage_service = TokenUsageService(poll_interval=120)
        self.token_usage_service.start()

        # Start status watcher
        self.start_status_watcher()

        # Start display rendering
        self.start_display()

        # Start background refresh loop
        self.start_background_loop()

        # Initial refresh
        self.refresh_all()

    def stop(self):
        """Stop the daemon."""
        if not self.running:
            return

        self.running = False

        # Stop config watcher
        if hasattr(self, 'config_watcher') and self.config_watcher:
            self.config_watcher.stop()

        self.stop_background_loop()
        self.stop_status_watcher()
        self.stop_display()
        self.socket_server.stop()
        self.command_server.stop()

        # Stop token usage service
        if self.token_usage_service:
            self.token_usage_service.stop()

    def run(self):
        """Run the daemon until interrupted."""
        self.start()
        try:
            while self.running:
                if self.background_thread and not self.background_thread.is_alive():
                    self.start_background_loop()
                if self.display_thread and not self.display_thread.is_alive():
                    self.start_display()

                time.sleep(5)
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
        daemon = CentralHubDaemon()
        daemon.refresh_all()
    else:
        daemon = CentralHubDaemon()
        daemon.run()


if __name__ == "__main__":
    main()
