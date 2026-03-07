"""Hook event processing for Claude Code status updates.

Handles the translation of raw hook events (PreToolUse, PostToolUse, Stop,
etc.) into semantic statuses, special animation triggers, and staleness
detection.
"""

from datetime import datetime

from ..core.state import StateStore
from ..services.session_tracker import SessionTracker
from .tool_classifier import classify_tool


class HookProcessor:
    """Processes raw Claude Code hook events into semantic statuses.

    Depends on StateStore and SessionTracker for state access, and
    delegates tool classification to the standalone classify_tool function.
    """

    def __init__(
        self,
        state: StateStore,
        session_tracker: SessionTracker,
    ):
        self.state = state
        self.session_tracker = session_tracker

    def process_hook_event(self, raw_data: dict) -> dict:
        """Process raw hook event into a semantic status dict."""
        session_id = raw_data.get("session_id", "unknown")
        event = raw_data.get("hook_event_name", "")
        tool_name = raw_data.get("tool_name", "")
        tool_error = raw_data.get("tool_error")

        if event == "PreToolUse":
            status = classify_tool(tool_name)
        elif event == "PostToolUse":
            status = "reviewing" if tool_error else "thinking"
        elif event == "UserPromptSubmit":
            status = "thinking"
        elif event == "Stop":
            status = self._check_special_animation(session_id) or "awaiting"
        elif event == "Notification":
            status = "awaiting"
        else:
            status = "idle"

        # Update session history with tool info and outcome
        tool_succeeded = not bool(tool_error) if event == "PostToolUse" else None
        self.session_tracker.update(session_id, status, tool_name, tool_succeeded)

        session = self.session_tracker.get(session_id)

        return {
            "session_id": session_id,
            "status": status,
            "status_history": session.get("status_history", []).copy(),
            "tool_history": session.get("tool_history", []).copy(),
            "tool_outcomes": session.get("tool_outcomes", []).copy(),
            "timestamp": datetime.now().isoformat(),
        }

    def _check_special_animation(self, session_id: str) -> str | None:
        """Check if Stop event should trigger a special animation.

        Returns a status string if special animation should play, None otherwise.

        Triggers:
        - eureka: Created something (Write/Edit succeeded)
        - celebration: Productive session (5+ tools) without creation
        """
        session = self.session_tracker.get(session_id)
        tool_history = session.get("tool_history", [])
        tool_outcomes = session.get("tool_outcomes", [])

        if len(tool_history) < 3:
            return None

        creative_tools = {"Write", "Edit", "NotebookEdit"}
        recent_tools = tool_history[-5:]

        recent_outcomes = tool_outcomes[-5:]
        had_creative_success = any(
            o.get("tool") in creative_tools and o.get("succeeded", False) for o in recent_outcomes
        )

        if had_creative_success:
            return "eureka"

        # Fallback: check tool history if outcomes not tracked yet
        if any(t in creative_tools for t in recent_tools):
            return "eureka"

        if len(tool_history) >= 5:
            return "celebration"

        return None

    def check_status_staleness(self, timeout_seconds: int = 30) -> bool:
        """Check if status is stale and reset to idle if so.

        Returns True if status was reset, False otherwise.
        """
        status = self.state.get("status")
        if not status:
            return False

        timestamp_str = status.get("timestamp")
        current_status = status.get("status", "idle")

        # Don't reset if already idle or awaiting (these are resting states)
        if current_status in ("idle", "awaiting"):
            return False

        if not timestamp_str:
            return False

        try:
            last_update = datetime.fromisoformat(timestamp_str)
            age = datetime.now() - last_update
            if age.total_seconds() > timeout_seconds:
                stale_status = {
                    **status,
                    "status": "idle",
                    "timestamp": datetime.now().isoformat(),
                }
                self.state.update("status", stale_status)
                return True
        except (ValueError, TypeError):
            pass

        return False
