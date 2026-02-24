"""IPC command handlers for daemon hook events and state queries.

Each handler is a thin wrapper that queries StateStore or delegates to
the appropriate service (refresh, session_tracker, etc.).
"""

from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from .context import AppContext

from ..services.thinking_feed import get_session_manager
from .ipc import DaemonServer
from .refresh_manager import RefreshManager
from .session_tracker import SessionTracker


class CommandHandlers:
    """Registers and implements IPC command handlers for the daemon.

    All state access goes through the injected StateStore. Service
    delegation goes through the injected manager instances.
    """

    def __init__(
        self,
        ctx: "AppContext",
        session_tracker: SessionTracker,
        refresh: RefreshManager,
        command_server: DaemonServer,
        services: dict[str, Callable[[], Any | None]] | None = None,
    ):
        self.ctx = ctx
        self.session_tracker = session_tracker
        self.refresh = refresh
        self.command_server = command_server
        svc = services or {}
        self._get_voice_orchestrator = svc.get("voice", lambda: None)
        self._get_memory_service = svc.get("memory", lambda: None)
        self._get_ingestion_pipeline = svc.get("ingestion", lambda: None)
        self._get_agents = svc.get("agents", lambda: {})

    def register_all(self) -> None:
        """Register all command handlers with the IPC server."""
        reg = self.command_server.register

        # State queries
        reg("get_state", self.get_state)
        reg("get_status", self.get_status)
        reg("get_weather", self.get_weather)
        reg("get_sessions", self.get_sessions)
        reg("get_session", self.get_session)

        # Actions
        reg("refresh_weather", self.refresh.refresh_weather)
        reg("refresh_time", self.refresh.refresh_time)
        reg("refresh_location", self.refresh_location)
        reg("refresh_all", self.refresh_all)

        # Thinking context
        reg("get_thinking_context", self.get_thinking_context)

        # Voice context
        reg("get_voice_context", self.get_voice_context)

        # Voice session management
        reg("reset_voice_session", self.reset_voice_session)

        # Memory
        reg("memory_ingest", self.memory_ingest)

        # Agent management
        reg("reload_agents", self.reload_agents)

        # Utility
        reg("ping", lambda: "pong")

    # --- State queries ---

    def get_state(self) -> dict:
        """Get full Clarvis state."""
        status = self.ctx.state.get("status")
        weather = self.ctx.state.get("weather")
        time_data = self.ctx.state.get("time")
        sessions = self.ctx.state.get("sessions")

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
        return self.ctx.state.get("status")

    def get_weather(self) -> dict:
        """Get current weather."""
        return self.ctx.state.get("weather")

    def get_sessions(self) -> list:
        """List all tracked sessions."""
        return self.session_tracker.list_all()

    def get_session(self, session_id: str) -> dict:
        """Get details for a specific session."""
        return self.session_tracker.get_details(session_id)

    # --- Actions ---

    def refresh_location(self) -> dict:
        """Refresh location and return new data."""
        lat, lon, city = self.refresh.refresh_location()
        return {"latitude": lat, "longitude": lon, "city": city}

    def refresh_all(self) -> str:
        """Refresh all data sources."""
        self.refresh.refresh_all()
        return "ok"

    # --- Thinking context ---

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

    # --- Voice context ---

    def get_voice_context(self) -> dict:
        """Return the context snapshot that would be prepended to a voice command."""
        status = self.ctx.state.get("status")
        weather = self.ctx.state.get("weather")
        time_data = self.ctx.state.get("time")

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

        orchestrator = self._get_voice_orchestrator()
        ctx["formatted"] = orchestrator.build_voice_context() if orchestrator else ""

        return ctx

    # --- Voice session management ---

    def reset_voice_session(self) -> str:
        """Disconnect voice agent so next interaction starts a fresh session."""
        import asyncio
        from pathlib import Path

        # Remove agent session ID files so next interaction starts fresh
        for sid_file in [
            Path.home() / ".clarvis" / "home" / "session_id",
            Path.home() / ".clarvis" / "channels" / "session_id",
        ]:
            sid_file.unlink(missing_ok=True)

        # Disconnect voice agent (it'll reconnect fresh on next voice command)
        orchestrator = self._get_voice_orchestrator()
        if orchestrator and orchestrator.agent.connected:
            asyncio.run_coroutine_threadsafe(orchestrator.agent.disconnect(), orchestrator._loop)

        return "ok"

    def reload_agents(self, **kwargs) -> dict:
        """Reload agent prompts and context files (CLAUDE.md / AGENTS.md).

        For Pi backends, triggers session.reload() which re-reads context files,
        skills, and extensions. For Claude Code backends, this is a no-op since
        CLAUDE.md is re-read per turn.
        """
        import asyncio

        agents = self._get_agents()
        if not agents:
            return {"error": "No agents initialized"}

        reloaded = []
        errors = []

        for name, agent in agents.items():
            backend = getattr(agent, "_backend", None)
            reload_fn = getattr(backend, "reload", None)
            if reload_fn is None:
                reloaded.append(f"{name}: skipped (no reload support)")
                continue
            try:
                loop = getattr(agent, "_loop", None)
                if loop is None:
                    errors.append(f"{name}: no event loop")
                    continue
                asyncio.run_coroutine_threadsafe(reload_fn(), loop).result(timeout=15)
                reloaded.append(f"{name}: ok")
            except Exception as exc:
                errors.append(f"{name}: {exc}")

        return {"status": "ok", "reloaded": reloaded, "errors": errors}

    def memory_ingest(self, **kwargs) -> dict:
        """Trigger manual memory ingestion (called by `clarvis rem`)."""
        import asyncio

        pipeline = self._get_ingestion_pipeline()
        mem_svc = self._get_memory_service()
        if not pipeline or not mem_svc:
            return {"error": "Memory service not available"}

        if not mem_svc.ready:
            return {"error": "Memory service not started"}

        # Find active sessions to ingest
        sessions = self.session_tracker.list_all()
        if not sessions:
            # Check staleness as fallback info
            stale = pipeline.is_stale()
            return {"status": "ok", "ingested": 0, "stale": stale}

        ingested = 0
        errors = []
        loop = self.ctx.loop
        for sess in sessions:
            transcript = sess.get("transcript_path")
            session_key = sess.get("session_id", "unknown")
            if not transcript:
                continue
            try:
                result = asyncio.run_coroutine_threadsafe(
                    pipeline.ingest_session(
                        session_key,
                        transcript,
                        dataset="parletre",
                    ),
                    loop,
                ).result(timeout=30)
                if result.get("status") == "ok":
                    ingested += 1
            except Exception as exc:
                errors.append(str(exc))

        return {"status": "ok", "ingested": ingested, "errors": errors}
