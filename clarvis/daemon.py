#!/usr/bin/env python3
"""Background daemon for Clarvis - handles status processing and data refreshes."""

from __future__ import annotations

import atexit
import fcntl
import json
import os
import signal
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from .core import read_hub_data
from .core.state import StateStore, get_state_store
from .core.session_tracker import SessionTracker
from .core.display_manager import DisplayManager
from .core.refresh_manager import RefreshManager
from .core.ipc import DaemonServer
from .services.token_usage import TokenUsageService
from .services.thinking_feed import get_session_manager
from .services.whimsy_verb import WhimsyManager
from .widget.renderer import FrameRenderer
from .widget.config import get_config, watch_config, WidgetConfig, restart_daemon_and_widget
from .widget.socket_server import WidgetSocketServer, get_socket_server


class PidLock:
    """Ensures only one daemon instance runs at a time using PID file locking.

    Features:
    - Atomic locking with fcntl.flock()
    - Stale PID detection (handles crashed processes)
    - Signal handler registration for cleanup
    - Context manager support
    """

    DEFAULT_PID_FILE = Path("/tmp/clarvis-daemon.pid")

    def __init__(self, pid_file: Path = None):
        self.pid_file = pid_file or self.DEFAULT_PID_FILE
        self._lock_fd: Optional[int] = None
        self._original_handlers: Dict[int, Any] = {}

    def acquire(self) -> bool:
        """Attempt to acquire the daemon lock.

        Returns:
            True if lock acquired, False if another instance is running.
        """
        # Check for stale PID file first
        if self.pid_file.exists():
            try:
                old_pid = int(self.pid_file.read_text().strip())
                # Check if process is actually running
                os.kill(old_pid, 0)  # Signal 0 = check existence
                # Process exists - check if we can get the lock anyway
            except (ValueError, ProcessLookupError, PermissionError):
                # PID file is stale (process doesn't exist or invalid)
                try:
                    self.pid_file.unlink()
                except OSError:
                    pass

        # Open/create PID file
        try:
            self._lock_fd = os.open(
                str(self.pid_file),
                os.O_RDWR | os.O_CREAT,
                0o644
            )
        except OSError as e:
            print(f"Error: Cannot create PID file {self.pid_file}: {e}", file=sys.stderr)
            return False

        # Try to acquire exclusive lock (non-blocking)
        try:
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (IOError, OSError):
            # Another process holds the lock
            os.close(self._lock_fd)
            self._lock_fd = None
            try:
                existing_pid = self.pid_file.read_text().strip()
                print(f"Error: Daemon already running (PID {existing_pid})", file=sys.stderr)
            except Exception:
                print("Error: Daemon already running", file=sys.stderr)
            return False

        # Write our PID
        os.ftruncate(self._lock_fd, 0)
        os.write(self._lock_fd, f"{os.getpid()}\n".encode())
        os.fsync(self._lock_fd)

        # Register cleanup handlers
        self._register_signal_handlers()
        atexit.register(self.release)

        return True

    def release(self) -> None:
        """Release the daemon lock and clean up."""
        if self._lock_fd is not None:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                os.close(self._lock_fd)
            except OSError:
                pass
            self._lock_fd = None

        # Remove PID file
        try:
            self.pid_file.unlink()
        except OSError:
            pass

        # Restore original signal handlers
        for sig, handler in self._original_handlers.items():
            signal.signal(sig, handler)
        self._original_handlers.clear()

    def _register_signal_handlers(self) -> None:
        """Register signal handlers for graceful cleanup."""
        def cleanup_handler(signum, frame):
            self.release()
            # Re-raise with default handler for proper exit
            signal.signal(signum, signal.SIG_DFL)
            os.kill(os.getpid(), signum)

        for sig in (signal.SIGTERM, signal.SIGINT):
            self._original_handlers[sig] = signal.signal(sig, cleanup_handler)

    def __enter__(self) -> "PidLock":
        if not self.acquire():
            raise RuntimeError("Failed to acquire daemon lock")
        return self

    def __exit__(self, *args) -> None:
        self.release()


# Global lock instance for daemon
_daemon_lock: Optional[PidLock] = None


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
    """Background daemon for Clarvis - uses StateStore as single source of truth."""

    def __init__(
        self,
        status_raw_file: Path = None,
        hub_data_file: Path = None,
        output_file: Path = None,
        refresh_interval: int = 30,
        display_fps: int = None,  # Now defaults to config value
        state_store: StateStore = None,
        socket_server: WidgetSocketServer = None,
    ):
        # File paths
        self.status_raw_file = status_raw_file or Path("/tmp/claude-status-raw.json")
        self.hub_data_file = hub_data_file or Path("/tmp/clarvis-data.json")
        self.output_file = output_file or Path("/tmp/widget-display.json")
        self.refresh_interval = refresh_interval

        # Load config
        config = get_config()
        
        # Use config FPS if not explicitly provided
        self.display_fps = display_fps if display_fps is not None else config.display.fps

        # Core state
        self.state = state_store or get_state_store()
        self.session_tracker = SessionTracker(self.state)
        self.command_server = DaemonServer()
        self.token_usage_service: Optional[TokenUsageService] = None

        # Threading
        self.observer: Observer | None = None
        self.running = False
        self._lock = threading.Lock()

        # Display manager with pre-warmed renderer
        renderer = FrameRenderer(
            width=config.grid_width,
            height=config.grid_height,
            avatar_x_offset=config.display.avatar_x_offset,
            avatar_y_offset=config.display.avatar_y_offset,
            bar_x_offset=config.display.bar_x_offset,
            bar_y_offset=config.display.bar_y_offset,
        )
        self.socket_server = socket_server or get_socket_server()
        self.display = DisplayManager(
            renderer=renderer,
            socket_server=self.socket_server,
            output_file=self.output_file,
            fps=self.display_fps,
        )

        # Whimsy verb manager
        self.whimsy = WhimsyManager(
            context_provider=lambda: self._get_rich_context(),
        )

        # Refresh manager (created after display for dependency)
        self.refresh = RefreshManager(
            state=self.state,
            display_manager=self.display,
            interval=refresh_interval,
        )

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

        # Initialize display from loaded state
        status = self.state.get("status")
        if status:
            self.display.set_status(status.get("status", "idle"))

        weather = self.state.get("weather")
        if weather:
            weather_type = weather.get("widget_type", "clear")
            intensity = weather.get("widget_intensity", 0.0)
            wind_speed = weather.get("wind_speed", 0.0)
            self.display.set_weather(weather_type, intensity, wind_speed)

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

    # --- Status Processing ---

    def process_hook_event(self, raw_data: dict) -> dict:
        """Process raw hook event into status/color based on tool_name."""
        session_id = raw_data.get("session_id", "unknown")
        event = raw_data.get("hook_event_name", "")
        tool_name = raw_data.get("tool_name", "")
        context_window = raw_data.get("context_window") or {}
        context_percent = context_window.get("used_percentage") or 0

        # Get existing status from state
        existing_status = self.state.get("status")

        # Tool categories for semantic status mapping
        READING_TOOLS = {"Read", "Grep", "Glob", "WebFetch", "WebSearch"}
        WRITING_TOOLS = {"Write", "Edit"}
        EXECUTING_TOOLS = {"Bash"}
        THINKING_TOOLS = {"Task"}
        AWAITING_TOOLS = {"AskUserQuestion"}

        # Map events to status/color with tool-based refinement
        if event == "PreToolUse":
            # Use tool_name to determine specific status
            if tool_name in READING_TOOLS or tool_name.startswith("mcp__") and "read" in tool_name.lower():
                status, color = "reading", "cyan"
            elif tool_name in WRITING_TOOLS:
                status, color = "writing", "magenta"
            elif tool_name in EXECUTING_TOOLS:
                status, color = "executing", "orange"
            elif tool_name in THINKING_TOOLS:
                status, color = "thinking", "yellow"
            elif tool_name in AWAITING_TOOLS:
                status, color = "awaiting", "blue"
            else:
                # Default for unknown tools
                status, color = "running", "green"
        elif event == "PostToolUse":
            status, color = "thinking", "yellow"
        elif event == "UserPromptSubmit":
            status, color = "thinking", "yellow"
        elif event == "Stop":
            # Check for special animation triggers
            special = self._check_special_animation(session_id, raw_data)
            if special:
                status, color = special
            else:
                status, color = "awaiting", "blue"
        elif event == "Notification":
            status, color = "awaiting", "blue"
        elif context_window:
            status = existing_status.get("status", "idle")
            color = existing_status.get("color", "gray")
        else:
            status, color = "idle", "gray"

        # Update session history with tool info
        self.session_tracker.update(session_id, status, context_percent, tool_name)

        # Use last known context if current is 0
        effective_context = context_percent or self.session_tracker.get_last_context(session_id)

        # Get session data for output
        session = self.session_tracker.get(session_id)

        return {
            "session_id": session_id,
            "status": status,
            "color": color,
            "context_percent": effective_context,
            "status_history": session.get("status_history", []).copy(),
            "context_history": session.get("context_history", []).copy(),
            "tool_history": session.get("tool_history", []).copy(),
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

            # Update display if this is the displayed session
            if processed.get("session_id") == self.session_tracker.displayed_id:
                self.display.set_status(processed.get("status", "idle"))

            # Trigger whimsy verb on user prompt submit (with cooldown)
            self._maybe_trigger_whimsy(raw_data.get("hook_event_name"))

            # Periodically clean up stale sessions
            self.session_tracker.cleanup_stale()

        except (json.JSONDecodeError, IOError):
            pass


    def _check_special_animation(self, session_id: str, raw_data: dict) -> tuple[str, str] | None:
        """Check if Stop event should trigger a special animation.
        
        Returns (status, color) tuple if special animation should play, None otherwise.
        
        Triggers:
        - celebration: Stop after 5+ tool uses in session (productive work)
        - eureka: Stop after Write/Edit in recent tool history (created something)
        """
        session = self.session_tracker.get(session_id)
        tool_history = session.get("tool_history", [])
        
        # Need some activity to trigger special animations
        if len(tool_history) < 3:
            return None
        
        # Check for productive session (5+ tools = celebration)
        if len(tool_history) >= 5:
            # Check if recent tools include Write/Edit (created something = eureka)
            recent_tools = tool_history[-5:]
            creative_tools = {"Write", "Edit"}
            if any(t in creative_tools for t in recent_tools):
                return ("eureka", "gold")
            else:
                return ("celebration", "gold")
        
        # Check for any Write/Edit in shorter sessions
        if any(t in {"Write", "Edit"} for t in tool_history[-3:]):
            return ("eureka", "gold")
        
        return None

    def _maybe_trigger_whimsy(self, event: str | None):
        """Trigger whimsy verb generation when switching to thinking status."""
        if event:
            self.whimsy.maybe_generate(event)

    def _get_rich_context(self, max_messages: int = 5, max_chars: int = 1200) -> str:
        """Build compact context for whimsy verb generation (~400 tokens).

        Combines: weather, time, music, activity, conversation.
        """
        parts = []

        # Weather + Time (compact)
        weather = self.state.get("weather")
        if weather and weather.get("temperature"):
            temp = weather.get("temperature", "")
            desc = weather.get("description", "").lower()
            parts.append(f"{temp}°F {desc}")

        time_data = self.state.get("time")
        if time_data and time_data.get("timestamp"):
            try:
                dt = datetime.fromisoformat(time_data["timestamp"])
                hour = dt.hour
                period = "morning" if 5 <= hour < 12 else "afternoon" if 12 <= hour < 17 else "evening" if 17 <= hour < 21 else "night"
                parts.append(f"{dt.strftime('%A')} {period}")
            except (ValueError, KeyError):
                pass

        # Music (compact)
        try:
            from clautify import Clautify
            now = Clautify().now_playing()
            if now and now.get("state") == "PLAYING":
                title = now.get("title", "")[:30]
                artist = now.get("artist", "")[:20]
                if title and artist:
                    parts.append(f"playing: {title} by {artist}")
        except Exception:
            pass

        # Activity (compact)
        status = self.state.get("status")
        if status and status.get("tool_history"):
            tools = list(dict.fromkeys(status["tool_history"][-3:]))
            parts.append(f"activity: {', '.join(t.lower() for t in tools)}")

        # Conversation (bulk of context)
        chat = self._get_chat_context(max_messages, max_msg_len=150)
        if chat:
            parts.append(f"chat:\n{chat}")

        result = "\n".join(parts)
        return result[:max_chars] if len(result) > max_chars else result

    def _get_chat_context(self, max_messages: int = 5, max_msg_len: int = 150) -> str:
        """Extract recent chat context from transcript file (compact format)."""
        try:
            if not self.status_raw_file.exists():
                return ""

            raw_data = json.loads(self.status_raw_file.read_text())
            transcript_path = raw_data.get("transcript_path")

            if not transcript_path or not Path(transcript_path).exists():
                return ""

            messages = []
            with open(transcript_path, 'r') as f:
                lines = f.readlines()

            for line in reversed(lines[-50:]):
                try:
                    entry = json.loads(line)
                    entry_type = entry.get("type")

                    if entry_type in ("user", "assistant"):
                        content = entry.get("message", {}).get("content", "")

                        if isinstance(content, list):
                            texts = [c.get("text", "") for c in content
                                     if c.get("type") == "text" and not c.get("text", "").startswith("<system")]
                            content = " ".join(texts)

                        if content and not content.startswith("<system"):
                            role = "U" if entry_type == "user" else "A"
                            # Truncate and clean
                            content = content[:max_msg_len].replace("\n", " ").strip()
                            messages.append(f"{role}: {content}")

                            if len(messages) >= max_messages:
                                break
                except json.JSONDecodeError:
                    continue

            messages.reverse()
            return "\n".join(messages)

        except Exception as e:
            return ""

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

    # --- Lifecycle ---

    def _on_config_change(self, new_config: WidgetConfig):
        """Handle config file changes."""
        # Check if grid size changed (requires restart)
        if (new_config.grid_width != self.display.renderer.width or
            new_config.grid_height != self.display.renderer.height):
            print(f"Grid size changed, restarting...")
            restart_daemon_and_widget()
            return

        # If testing mode, apply overrides immediately
        if new_config.testing.enabled:
            self.display.set_status(new_config.test_status)
            self.display.set_weather(
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

        # Whimsy verbs
        self.command_server.register("get_thinking_context", self._cmd_get_thinking_context)
        self.command_server.register("get_whimsy_verb", self._cmd_get_whimsy_verb)
        self.command_server.register("get_whimsy_stats", self._cmd_get_whimsy_stats)

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
        return self.session_tracker.list_all()

    def _cmd_get_session(self, session_id: str) -> dict:
        """Get details for a specific session."""
        return self.session_tracker.get_details(session_id)

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
        return self.refresh.refresh_weather(latitude, longitude)

    def _cmd_refresh_time(self, timezone: str = None) -> dict:
        """Refresh time and return new data."""
        return self.refresh.refresh_time(timezone)

    def _cmd_refresh_location(self) -> dict:
        """Refresh location and return new data."""
        lat, lon, city = self.refresh.refresh_location()
        return {"latitude": lat, "longitude": lon, "city": city}

    def _cmd_refresh_all(self) -> str:
        """Refresh all data sources."""
        self.refresh.refresh_all()
        return "ok"

    def _cmd_get_thinking_context(self, limit: int = 500) -> dict:
        """Get latest thinking context from active sessions."""
        manager = get_session_manager()
        latest = manager.get_latest_thought()
        if not latest:
            return {"context": None, "session_id": None}

        # Truncate to limit
        text = latest.get("text", "")
        if len(text) > limit:
            text = text[-limit:]

        return {
            "context": text,
            "session_id": latest.get("session_id"),
            "project": latest.get("project"),
            "timestamp": latest.get("timestamp"),
        }

    def _cmd_get_whimsy_verb(self, context: str = None) -> dict:
        """Generate whimsy verb from context or latest thinking."""
        if not context:
            ctx_data = self._cmd_get_thinking_context()
            context = ctx_data.get("context")

        return self.whimsy.generate_sync(context)

    def _cmd_get_whimsy_stats(self) -> dict:
        """Get whimsy verb usage statistics."""
        return self.whimsy.stats

    def _get_display_state(self) -> tuple[str, float, str | None]:
        """Get current display state for rendering.

        Returns:
            Tuple of (status, context_percent, whimsy_verb)
        """
        config = get_config()

        if config.testing.enabled:
            # Testing mode overrides
            self.display.set_status(config.test_status)
            self.display.set_weather(
                config.test_weather,
                config.test_weather_intensity,
                config.test_wind_speed
            )
            return config.test_status, config.test_context_percent, self.whimsy.current_verb

        status = self.state.get("status")
        context_percent = status.get("context_percent", 0) if status else 0
        display_status = status.get("status", "idle") if status else "idle"
        return display_status, context_percent, self.whimsy.current_verb

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
        config = get_config()
        if config.token_usage.enabled:
            self.token_usage_service = TokenUsageService(
                poll_interval=config.token_usage.poll_interval
            )
            self.token_usage_service.start()

        # Start status watcher
        self.start_status_watcher()

        # Start display rendering (pass state getter callback)
        self.display.start(self._get_display_state)

        # Start background refresh loop
        self.refresh.start()

        # Initial refresh
        self.refresh.refresh_all()

    def stop(self):
        """Stop the daemon."""
        if not self.running:
            return

        self.running = False

        # Stop config watcher
        if hasattr(self, 'config_watcher') and self.config_watcher:
            self.config_watcher.stop()

        self.refresh.stop()
        self.stop_status_watcher()
        self.display.stop()
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
                # Restart managers if their threads died unexpectedly
                if self.refresh._thread and not self.refresh._thread.is_alive():
                    self.refresh.start()
                if self.display._thread and not self.display._thread.is_alive():
                    self.display.start(self._get_display_state)

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
    return get_daemon().refresh.refresh_location()


def refresh_weather(latitude: float = None, longitude: float = None, city: str = None) -> dict:
    """Refresh weather data and write to hub."""
    return get_daemon().refresh.refresh_weather(latitude, longitude, city)


def refresh_time(timezone: str = None) -> dict:
    """Refresh time data and write to hub."""
    return get_daemon().refresh.refresh_time(timezone)


def refresh_all():
    """Refresh all data sources."""
    get_daemon().refresh.refresh_all()


def main():
    """Entry point for daemon mode."""
    global _daemon_lock

    if len(sys.argv) > 1 and sys.argv[1] == "--refresh":
        # One-shot refresh doesn't need lock
        daemon = CentralHubDaemon()
        daemon.refresh.refresh_all()
    else:
        # Acquire singleton lock before starting daemon
        _daemon_lock = PidLock()
        if not _daemon_lock.acquire():
            sys.exit(1)

        try:
            daemon = CentralHubDaemon()
            daemon.run()
        finally:
            _daemon_lock.release()


if __name__ == "__main__":
    main()
