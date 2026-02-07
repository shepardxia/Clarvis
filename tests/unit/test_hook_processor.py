"""Tests for HookProcessor — event classification, staleness, special animations."""

from datetime import datetime, timedelta

import pytest

from clarvis.core.hook_processor import HookProcessor


@pytest.fixture
def processor(state, session_tracker):
    return HookProcessor(state=state, session_tracker=session_tracker)


# ── Event → Status mapping ──────────────────────────────────────────


class TestProcessHookEvent:
    @pytest.mark.parametrize(
        "event_name, tool_name, tool_error, expected",
        [
            ("PreToolUse", "Read", None, "reading"),
            ("PostToolUse", "Bash", "command failed", "reviewing"),
            ("PostToolUse", "Bash", None, "thinking"),
            ("UserPromptSubmit", None, None, "thinking"),
            ("Stop", None, None, "awaiting"),
            ("Notification", None, None, "awaiting"),
            ("SomethingNew", None, None, "idle"),
        ],
    )
    def test_event_to_status(self, processor, event_name, tool_name, tool_error, expected):
        event = {"session_id": "s1", "hook_event_name": event_name}
        if tool_name:
            event["tool_name"] = tool_name
        if tool_error:
            event["tool_error"] = tool_error
        assert processor.process_hook_event(event)["status"] == expected

    def test_context_window_preserves_existing_status(self, processor, state):
        state.update("status", {"status": "writing"})
        result = processor.process_hook_event(
            {"session_id": "s1", "hook_event_name": "", "context_window": {"used_percentage": 50}}
        )
        assert result["status"] == "writing"

    @pytest.mark.parametrize("pct, high", [(65, False), (80, True)])
    def test_context_percent(self, processor, pct, high):
        result = processor.process_hook_event(
            {
                "session_id": "s1",
                "hook_event_name": "PreToolUse",
                "tool_name": "Read",
                "context_window": {"used_percentage": pct},
            }
        )
        assert result["context_percent"] == pct
        assert result["high_context"] is high

    def test_result_keys(self, processor):
        result = processor.process_hook_event(
            {"session_id": "s1", "hook_event_name": "PreToolUse", "tool_name": "Read"}
        )
        for key in ("status_history", "context_history", "tool_history", "tool_outcomes", "timestamp"):
            assert key in result


# ── Special animations ──────────────────────────────────────────────


def _build_session(state, session_tracker, tools, outcomes):
    """Helper to populate a session with tool history and outcomes."""
    for tool in tools:
        session_tracker.update("s1", "working", 50.0, tool, tool_succeeded=True)
    sessions = state.get("sessions")
    sessions["s1"]["tool_outcomes"] = outcomes
    state.update("sessions", sessions)


class TestSpecialAnimation:
    def test_eureka_on_creative_success(self, processor, state, session_tracker):
        _build_session(
            state,
            session_tracker,
            ["Read", "Read", "Read", "Edit", "Read"],
            [{"tool": t, "succeeded": True} for t in ["Read", "Read", "Read", "Edit", "Read"]],
        )
        result = processor.process_hook_event({"session_id": "s1", "hook_event_name": "Stop"})
        assert result["status"] == "eureka"

    def test_celebration_on_productive_session(self, processor, state, session_tracker):
        _build_session(
            state,
            session_tracker,
            ["Read", "Grep", "Read", "Bash", "Read"],
            [{"tool": t, "succeeded": True} for t in ["Read", "Grep", "Read", "Bash", "Read"]],
        )
        result = processor.process_hook_event({"session_id": "s1", "hook_event_name": "Stop"})
        assert result["status"] == "celebration"

    def test_no_animation_for_short_session(self, processor, state, session_tracker):
        _build_session(state, session_tracker, ["Read", "Edit"], [{"tool": "Read", "succeeded": True}])
        result = processor.process_hook_event({"session_id": "s1", "hook_event_name": "Stop"})
        assert result["status"] == "awaiting"


# ── Staleness ───────────────────────────────────────────────────────


class TestStaleness:
    @pytest.mark.parametrize(
        "status, age_secs, expected_reset",
        [
            ("reading", 60, True),
            ("reading", 5, False),
            ("idle", 60, False),
            ("awaiting", 60, False),
        ],
    )
    def test_staleness(self, processor, state, status, age_secs, expected_reset):
        state.update(
            "status",
            {"status": status, "timestamp": (datetime.now() - timedelta(seconds=age_secs)).isoformat()},
        )
        assert processor.check_status_staleness(timeout_seconds=30) is expected_reset

    def test_empty_status_not_reset(self, processor, state):
        assert processor.check_status_staleness() is False
