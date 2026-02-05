"""Tests for HookProcessor — event classification, staleness, special animations."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from clarvis.core.state import StateStore
from clarvis.core.session_tracker import SessionTracker
from clarvis.core.hook_processor import HookProcessor


@pytest.fixture
def processor(state, session_tracker):
    """HookProcessor with a real StateStore and SessionTracker."""
    return HookProcessor(
        state=state,
        session_tracker=session_tracker,
    )


class TestProcessHookEvent:
    def test_pre_tool_use_classifies_tool(self, processor):
        result = processor.process_hook_event({
            "session_id": "s1",
            "hook_event_name": "PreToolUse",
            "tool_name": "Read",
        })
        assert result["status"] == "reading"
        assert result["session_id"] == "s1"
        assert "color" not in result  # color was removed from pipeline

    def test_post_tool_use_with_error(self, processor):
        result = processor.process_hook_event({
            "session_id": "s1",
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_error": "command failed",
        })
        assert result["status"] == "reviewing"

    def test_post_tool_use_without_error(self, processor):
        result = processor.process_hook_event({
            "session_id": "s1",
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
        })
        assert result["status"] == "thinking"

    def test_user_prompt_submit(self, processor):
        result = processor.process_hook_event({
            "session_id": "s1",
            "hook_event_name": "UserPromptSubmit",
        })
        assert result["status"] == "thinking"

    def test_stop_event_defaults_to_awaiting(self, processor):
        result = processor.process_hook_event({
            "session_id": "s1",
            "hook_event_name": "Stop",
        })
        assert result["status"] == "awaiting"

    def test_notification_event(self, processor):
        result = processor.process_hook_event({
            "session_id": "s1",
            "hook_event_name": "Notification",
        })
        assert result["status"] == "awaiting"

    def test_context_window_preserves_existing_status(self, processor, state):
        state.update("status", {"status": "writing"})
        result = processor.process_hook_event({
            "session_id": "s1",
            "hook_event_name": "",
            "context_window": {"used_percentage": 50},
        })
        assert result["status"] == "writing"

    def test_unknown_event_defaults_to_idle(self, processor):
        result = processor.process_hook_event({
            "session_id": "s1",
            "hook_event_name": "SomethingNew",
        })
        assert result["status"] == "idle"

    def test_context_percent_from_event(self, processor):
        result = processor.process_hook_event({
            "session_id": "s1",
            "hook_event_name": "PreToolUse",
            "tool_name": "Read",
            "context_window": {"used_percentage": 65},
        })
        assert result["context_percent"] == 65
        assert result["high_context"] is False

    def test_high_context_flag(self, processor):
        result = processor.process_hook_event({
            "session_id": "s1",
            "hook_event_name": "PreToolUse",
            "tool_name": "Read",
            "context_window": {"used_percentage": 80},
        })
        assert result["high_context"] is True

    def test_result_includes_history_copies(self, processor):
        result = processor.process_hook_event({
            "session_id": "s1",
            "hook_event_name": "PreToolUse",
            "tool_name": "Read",
        })
        assert "status_history" in result
        assert "context_history" in result
        assert "tool_history" in result
        assert "tool_outcomes" in result
        assert "timestamp" in result


class TestSpecialAnimation:
    def _build_session(self, state, session_tracker, tools, outcomes=None):
        """Helper to build a session with tool/outcome history."""
        for tool in tools:
            session_tracker.update("s1", "working", 50.0, tool, tool_succeeded=True)
        if outcomes:
            sessions = state.get("sessions")
            sessions["s1"]["tool_outcomes"] = outcomes
            state.update("sessions", sessions)

    def test_eureka_on_creative_success(self, processor, state, session_tracker):
        self._build_session(state, session_tracker, ["Read", "Read", "Read", "Edit", "Read"])
        # Simulate PostToolUse success for Edit
        sessions = state.get("sessions")
        sessions["s1"]["tool_outcomes"] = [
            {"tool": "Read", "succeeded": True},
            {"tool": "Read", "succeeded": True},
            {"tool": "Read", "succeeded": True},
            {"tool": "Edit", "succeeded": True},
            {"tool": "Read", "succeeded": True},
        ]
        state.update("sessions", sessions)

        result = processor.process_hook_event({
            "session_id": "s1",
            "hook_event_name": "Stop",
        })
        assert result["status"] == "eureka"

    def test_celebration_on_productive_session(self, processor, state, session_tracker):
        # 5+ tools, none creative
        self._build_session(state, session_tracker, ["Read", "Grep", "Read", "Bash", "Read"])
        # No creative tools in outcomes
        sessions = state.get("sessions")
        sessions["s1"]["tool_outcomes"] = [
            {"tool": "Read", "succeeded": True},
            {"tool": "Grep", "succeeded": True},
            {"tool": "Read", "succeeded": True},
            {"tool": "Bash", "succeeded": True},
            {"tool": "Read", "succeeded": True},
        ]
        state.update("sessions", sessions)

        result = processor.process_hook_event({
            "session_id": "s1",
            "hook_event_name": "Stop",
        })
        assert result["status"] == "celebration"

    def test_no_animation_for_short_session(self, processor, state, session_tracker):
        self._build_session(state, session_tracker, ["Read", "Edit"])
        result = processor.process_hook_event({
            "session_id": "s1",
            "hook_event_name": "Stop",
        })
        assert result["status"] == "awaiting"


class TestStaleness:
    def test_stale_status_resets_to_idle(self, processor, state):
        state.update("status", {
            "status": "reading",
            "timestamp": (datetime.now() - timedelta(seconds=60)).isoformat(),
        })
        assert processor.check_status_staleness(timeout_seconds=30) is True
        assert state.get("status")["status"] == "idle"

    def test_fresh_status_not_reset(self, processor, state):
        state.update("status", {
            "status": "reading",
            "timestamp": datetime.now().isoformat(),
        })
        assert processor.check_status_staleness(timeout_seconds=30) is False

    def test_idle_not_reset(self, processor, state):
        state.update("status", {
            "status": "idle",
            "timestamp": (datetime.now() - timedelta(seconds=60)).isoformat(),
        })
        assert processor.check_status_staleness(timeout_seconds=30) is False

    def test_awaiting_not_reset(self, processor, state):
        state.update("status", {
            "status": "awaiting",
            "timestamp": (datetime.now() - timedelta(seconds=60)).isoformat(),
        })
        assert processor.check_status_staleness(timeout_seconds=30) is False

    def test_empty_status_not_reset(self, processor, state):
        assert processor.check_status_staleness() is False
