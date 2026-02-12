"""Hook event processing for Claude Code status updates.

Handles the translation of raw hook events (PreToolUse, PostToolUse, Stop,
etc.) into semantic statuses, special animation triggers, staleness
detection, and context building for whimsy verb generation.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from .session_tracker import SessionTracker
from .state import StateStore

# --- Tool classification ---

READING_TOOLS = {"Read", "Grep", "Glob", "WebFetch", "WebSearch", "LS", "NotebookRead"}
WRITING_TOOLS = {"Write", "Edit", "NotebookEdit"}
EXECUTING_TOOLS = {"Bash", "TodoWrite", "TodoRead"}
THINKING_TOOLS = {"Task", "EnterPlanMode", "ExitPlanMode"}
AWAITING_TOOLS = {"AskUserQuestion"}

READING_KEYWORDS = {"read", "get", "list", "find", "search", "fetch", "query", "inspect", "browse", "view"}
WRITING_KEYWORDS = {"write", "create", "edit", "replace", "insert", "delete", "update", "add", "remove", "set"}
EXECUTING_KEYWORDS = {"execute", "run", "shell", "browser", "click", "navigate", "type", "press", "play", "pause"}


def classify_tool(tool_name: str) -> str:
    """Classify a tool into a semantic status based on its name."""
    if tool_name in READING_TOOLS:
        return "reading"
    if tool_name in WRITING_TOOLS:
        return "writing"
    if tool_name in EXECUTING_TOOLS:
        return "executing"
    if tool_name in THINKING_TOOLS:
        return "thinking"
    if tool_name in AWAITING_TOOLS:
        return "awaiting"

    if tool_name.startswith("mcp__"):
        lower = tool_name.lower()
        if any(kw in lower for kw in WRITING_KEYWORDS):
            return "writing"
        if any(kw in lower for kw in EXECUTING_KEYWORDS):
            return "executing"
        if any(kw in lower for kw in READING_KEYWORDS):
            return "reading"

    return "running"


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
        self.last_transcript_path: Optional[str] = None

    def process_hook_event(self, raw_data: dict) -> dict:
        """Process raw hook event into a semantic status dict."""
        session_id = raw_data.get("session_id", "unknown")
        event = raw_data.get("hook_event_name", "")
        tool_name = raw_data.get("tool_name", "")
        tool_error = raw_data.get("tool_error")
        context_window = raw_data.get("context_window") or {}
        context_percent = context_window.get("used_percentage") or 0

        existing_status = self.state.get("status")

        if event == "PreToolUse":
            status = classify_tool(tool_name)
        elif event == "PostToolUse":
            status = "reviewing" if tool_error else "thinking"
        elif event == "UserPromptSubmit":
            status = "thinking"
        elif event == "Stop":
            status = self._check_special_animation(session_id, raw_data) or "awaiting"
        elif event == "Notification":
            status = "awaiting"
        elif context_window:
            status = existing_status.get("status", "idle")
        else:
            status = "idle"

        # Update session history with tool info and outcome
        tool_succeeded = not bool(tool_error) if event == "PostToolUse" else None
        self.session_tracker.update(session_id, status, context_percent, tool_name, tool_succeeded)

        # Use last known context if current is 0
        effective_context = context_percent or self.session_tracker.get_last_context(session_id)

        session = self.session_tracker.get(session_id)

        return {
            "session_id": session_id,
            "status": status,
            "context_percent": effective_context,
            "high_context": effective_context >= 70,
            "status_history": session.get("status_history", []).copy(),
            "context_history": session.get("context_history", []).copy(),
            "tool_history": session.get("tool_history", []).copy(),
            "tool_outcomes": session.get("tool_outcomes", []).copy(),
            "timestamp": datetime.now().isoformat(),
        }

    def _check_special_animation(self, session_id: str, raw_data: dict) -> Optional[str]:
        """Check if Stop event should trigger a special animation.

        Returns a status string if special animation should play, None otherwise.

        Triggers:
        - eureka: Created something (Write/Edit succeeded), especially after failures
        - celebration: Productive session (5+ tools) without creation
        """
        session = self.session_tracker.get(session_id)
        tool_history = session.get("tool_history", [])
        tool_outcomes = session.get("tool_outcomes", [])

        if len(tool_history) < 3:
            return None

        creative_tools = {"Write", "Edit", "NotebookEdit"}
        recent_tools = tool_history[-5:] if len(tool_history) >= 5 else tool_history

        recent_outcomes = tool_outcomes[-5:] if len(tool_outcomes) >= 5 else tool_outcomes
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

    def get_rich_context(self, max_messages: int = 5, max_chars: int = 1500) -> str:
        """Build task-focused context for whimsy verb generation.

        Prioritizes what Claude is doing over ambient info.
        """
        parts = []

        # --- PRIMARY: What Claude is doing ---
        status = self.state.get("status")
        if status:
            current_status = status.get("status", "idle")
            parts.append(f"status: {current_status}")

            tool_history = status.get("tool_history", [])
            if tool_history:
                recent = tool_history[-3:]
                tool_actions = {
                    "Read": "reading code",
                    "Grep": "searching codebase",
                    "Glob": "finding files",
                    "Write": "writing new code",
                    "Edit": "editing code",
                    "Bash": "running commands",
                    "Task": "delegating to subagent",
                    "WebFetch": "fetching from web",
                    "WebSearch": "searching web",
                }
                actions = [tool_actions.get(t, t.lower()) for t in recent]
                parts.append(f"doing: {', '.join(actions)}")

            ctx_pct = status.get("context_percent", 0)
            if ctx_pct > 70:
                parts.append(f"context: {ctx_pct:.0f}% full (deep in complex task)")
            elif ctx_pct > 40:
                parts.append(f"context: {ctx_pct:.0f}% (working steadily)")

        # --- SECONDARY: Conversation (the actual task) ---
        chat = self._get_chat_context(max_messages, max_msg_len=200)
        if chat:
            parts.append(f"conversation:\n{chat}")

        # --- TERTIARY: Ambient context ---
        ambient = []

        weather = self.state.get("weather")
        if weather and weather.get("temperature"):
            desc = weather.get("description", "").lower()
            temp = weather.get("temperature", "")
            ambient.append(f"{temp}F {desc}")

        time_data = self.state.get("time")
        if time_data and time_data.get("timestamp"):
            try:
                dt = datetime.fromisoformat(time_data["timestamp"])
                hour = dt.hour
                if 5 <= hour < 12:
                    period = "morning"
                elif 12 <= hour < 17:
                    period = "afternoon"
                elif 17 <= hour < 21:
                    period = "evening"
                else:
                    period = "night"
                ambient.append(f"{dt.strftime('%A')} {period}")
            except (ValueError, KeyError):
                pass

        if ambient:
            parts.append(f"environment: {', '.join(ambient)}")

        result = "\n".join(parts)
        return result[:max_chars] if len(result) > max_chars else result

    def _get_chat_context(self, max_messages: int = 5, max_msg_len: int = 150) -> str:
        """Extract recent chat context from transcript file (compact format)."""
        try:
            transcript_path = self.last_transcript_path

            if not transcript_path or not Path(transcript_path).exists():
                return ""

            messages = []
            with open(transcript_path, "r") as f:
                lines = f.readlines()

            for line in reversed(lines[-50:]):
                try:
                    entry = json.loads(line)
                    entry_type = entry.get("type")

                    if entry_type in ("user", "assistant"):
                        content = entry.get("message", {}).get("content", "")

                        if isinstance(content, list):
                            texts = [
                                c.get("text", "")
                                for c in content
                                if c.get("type") == "text" and not c.get("text", "").startswith("<system")
                            ]
                            content = " ".join(texts)

                        if content and not content.startswith("<system"):
                            role = "U" if entry_type == "user" else "A"
                            content = content[:max_msg_len].replace("\n", " ").strip()
                            messages.append(f"{role}: {content}")

                            if len(messages) >= max_messages:
                                break
                except json.JSONDecodeError:
                    continue

            messages.reverse()
            return "\n".join(messages)

        except Exception:
            return ""
