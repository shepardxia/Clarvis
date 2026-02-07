"""Tracks Claude Code sessions with status and context history."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .state import StateStore


class SessionTracker:
    """Tracks Claude Code sessions with status and context history."""

    HISTORY_SIZE = 20
    TIMEOUT = 300  # 5 minutes

    def __init__(self, state: StateStore):
        self.state = state
        self.displayed_id: str | None = None

    def get(self, session_id: str) -> dict:
        """Get or create session data."""
        sessions = self.state.get("sessions")
        if session_id not in sessions:
            sessions[session_id] = {
                "status_history": [],
                "context_history": [],
                "tool_history": [],
                "tool_outcomes": [],
                "last_status": "idle",
                "last_context": 0.0,
                "last_tool": "",
                "last_seen": time.time(),
            }
            self.state.update("sessions", sessions)
        return sessions[session_id]

    @staticmethod
    def _append_capped(session: dict, key: str, value, max_size: int) -> None:
        """Append value to a capped history list in session dict."""
        lst = session.get(key, [])
        lst.append(value)
        if len(lst) > max_size:
            lst.pop(0)
        session[key] = lst

    def update(
        self,
        session_id: str,
        status: str,
        context: float,
        tool_name: str = "",
        tool_succeeded: bool | None = None,
    ) -> None:
        """Update session with new status, context, tool info, and outcome."""
        sessions = self.state.get("sessions")
        session = sessions.get(session_id) or {
            "status_history": [],
            "context_history": [],
            "tool_history": [],
            "tool_outcomes": [],
            "last_status": "idle",
            "last_context": 0.0,
            "last_tool": "",
        }

        session["last_seen"] = time.time()

        # Set displayed session if none set
        if self.displayed_id is None:
            self.displayed_id = session_id

        # Add status if changed (dedup: skip if same as last)
        history = session.get("status_history", [])
        if not history or history[-1] != status:
            self._append_capped(session, "status_history", status, self.HISTORY_SIZE)
        session["last_status"] = status

        # Add context if valid
        if context > 0:
            self._append_capped(session, "context_history", context, self.HISTORY_SIZE)
            session["last_context"] = context

        # Add tool if provided
        if tool_name:
            self._append_capped(session, "tool_history", tool_name, self.HISTORY_SIZE)
            session["last_tool"] = tool_name

        # Track tool outcome (success/failure) when known
        if tool_succeeded is not None and tool_name:
            self._append_capped(
                session, "tool_outcomes", {"tool": tool_name, "succeeded": tool_succeeded}, self.HISTORY_SIZE
            )

        sessions[session_id] = session
        self.state.update("sessions", sessions)

    def get_last_context(self, session_id: str) -> float:
        """Get last known context percent for session."""
        sessions = self.state.get("sessions")
        session = sessions.get(session_id, {})
        return session.get("last_context", 0.0)

    def cleanup_stale(self) -> None:
        """Remove sessions inactive for > TIMEOUT."""
        now = time.time()
        sessions = self.state.get("sessions")
        active = {sid: data for sid, data in sessions.items() if now - data.get("last_seen", 0) < self.TIMEOUT}
        if len(active) != len(sessions):
            self.state.update("sessions", active)
            if self.displayed_id not in active:
                self.displayed_id = next(iter(active), None)

    def list_all(self) -> list[dict]:
        """List all tracked sessions."""
        sessions = self.state.get("sessions")
        status = self.state.get("status")
        displayed = status.get("session_id") if status else None

        return [
            {
                "session_id": sid,
                "is_displayed": sid == displayed,
                "last_status": data.get("last_status", "unknown"),
                "last_context": data.get("last_context", 0),
                "status_history_length": len(data.get("status_history", [])),
                "context_history_length": len(data.get("context_history", [])),
            }
            for sid, data in sessions.items()
        ]

    def get_details(self, session_id: str) -> dict:
        """Get detailed info for a specific session."""
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
