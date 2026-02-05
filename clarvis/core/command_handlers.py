"""IPC command handlers for daemon-to-MCP-server communication.

Each handler is a thin wrapper that queries StateStore or delegates to
the appropriate service (refresh, whimsy, session_tracker, etc.).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .state import StateStore
from .session_tracker import SessionTracker
from .refresh_manager import RefreshManager
from .ipc import DaemonServer
from ..services.thinking_feed import get_session_manager
from ..services.whimsy_verb import WhimsyManager
from ..services.token_usage import TokenUsageService


class CommandHandlers:
    """Registers and implements IPC command handlers for the daemon.

    All state access goes through the injected StateStore. Service
    delegation goes through the injected manager instances.
    """

    def __init__(
        self,
        state: StateStore,
        session_tracker: SessionTracker,
        refresh: RefreshManager,
        whimsy: WhimsyManager,
        command_server: DaemonServer,
        token_usage_service_provider: callable,
        voice_orchestrator_provider: callable,
    ):
        self.state = state
        self.session_tracker = session_tracker
        self.refresh = refresh
        self.whimsy = whimsy
        self.command_server = command_server
        self._get_token_usage_service = token_usage_service_provider
        self._get_voice_orchestrator = voice_orchestrator_provider

    def register_all(self) -> None:
        """Register all command handlers with the IPC server."""
        reg = self.command_server.register

        # State queries
        reg("get_state", self.get_state)
        reg("get_status", self.get_status)
        reg("get_weather", self.get_weather)
        reg("get_sessions", self.get_sessions)
        reg("get_session", self.get_session)
        reg("get_token_usage", self.get_token_usage)

        # Actions
        reg("refresh_weather", self.refresh_weather)
        reg("refresh_time", self.refresh_time)
        reg("refresh_location", self.refresh_location)
        reg("refresh_all", self.refresh_all)

        # Whimsy verbs
        reg("get_thinking_context", self.get_thinking_context)
        reg("get_whimsy_verb", self.get_whimsy_verb)
        reg("get_whimsy_stats", self.get_whimsy_stats)

        # Voice context
        reg("get_voice_context", self.get_voice_context)

        # Utility
        reg("ping", lambda: "pong")

    # --- State queries ---

    def get_state(self) -> dict:
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

    def get_status(self) -> dict:
        """Get current status."""
        return self.state.get("status")

    def get_weather(self) -> dict:
        """Get current weather."""
        return self.state.get("weather")

    def get_sessions(self) -> list:
        """List all tracked sessions."""
        return self.session_tracker.list_all()

    def get_session(self, session_id: str) -> dict:
        """Get details for a specific session."""
        return self.session_tracker.get_details(session_id)

    def get_token_usage(self) -> Dict[str, Any]:
        """Get current token usage data."""
        service = self._get_token_usage_service()
        if not service:
            return {"error": "Token usage service not initialized", "is_stale": True}
        return service.get_usage()

    # --- Actions ---

    def refresh_weather(self, latitude: float = None, longitude: float = None) -> dict:
        """Refresh weather and return new data."""
        return self.refresh.refresh_weather(latitude, longitude)

    def refresh_time(self, timezone: str = None) -> dict:
        """Refresh time and return new data."""
        return self.refresh.refresh_time(timezone)

    def refresh_location(self) -> dict:
        """Refresh location and return new data."""
        lat, lon, city = self.refresh.refresh_location()
        return {"latitude": lat, "longitude": lon, "city": city}

    def refresh_all(self) -> str:
        """Refresh all data sources."""
        self.refresh.refresh_all()
        return "ok"

    # --- Whimsy verbs ---

    def get_thinking_context(self, limit: int = 500) -> dict:
        """Get latest thinking context from active sessions."""
        manager = get_session_manager()
        latest = manager.get_latest_thought()
        if not latest:
            return {"context": None, "session_id": None}

        text = latest.get("text", "")
        if len(text) > limit:
            text = text[-limit:]

        return {
            "context": text,
            "session_id": latest.get("session_id"),
            "project": latest.get("project"),
            "timestamp": latest.get("timestamp"),
        }

    def get_whimsy_verb(self, context: str = None) -> dict:
        """Generate whimsy verb from context or latest thinking."""
        if not context:
            ctx_data = self.get_thinking_context()
            context = ctx_data.get("context")
        return self.whimsy.generate_sync(context)

    def get_whimsy_stats(self) -> dict:
        """Get whimsy verb usage statistics."""
        return self.whimsy.stats

    # --- Voice context ---

    def get_voice_context(self) -> dict:
        """Return the context snapshot that would be prepended to a voice command."""
        status = self.state.get("status") or {}
        weather = self.state.get("weather") or {}
        time_data = self.state.get("time") or {}

        ctx: dict = {
            "status": status.get("status", "idle"),
            "context_percent": status.get("context_percent", 0),
            "tool_history": status.get("tool_history", [])[-5:],
        }

        if weather.get("temperature"):
            ctx["weather"] = {
                "temperature": weather.get("temperature"),
                "description": weather.get("description", ""),
            }

        if time_data.get("timestamp"):
            ctx["time"] = time_data["timestamp"]

        try:
            from clautify import Clautify
            now = Clautify().now_playing()
            if now and now.get("state") == "PLAYING":
                ctx["music"] = {
                    "title": now.get("title", ""),
                    "artist": now.get("artist", ""),
                }
        except Exception:
            pass

        orchestrator = self._get_voice_orchestrator()
        if orchestrator:
            ctx["formatted"] = orchestrator._build_voice_context()
        else:
            ctx["formatted"] = ""

        return ctx
