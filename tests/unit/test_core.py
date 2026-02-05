"""Tests for core modules: StateStore, SessionTracker, tool_classifier, colors."""

import time
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from clarvis.core.state import StateStore
from clarvis.core.session_tracker import SessionTracker
from clarvis.core.tool_classifier import (
    classify_tool,
    READING_TOOLS,
    WRITING_TOOLS,
    EXECUTING_TOOLS,
    THINKING_TOOLS,
    AWAITING_TOOLS,
)
from clarvis.core.colors import StatusColors, STATUS_MAP, ColorDef


# ── StateStore ──────────────────────────────────────────────────────

class TestStateStore:
    def test_initial_state_has_all_sections(self, state):
        for section in ("status", "sessions", "weather", "location", "time", "voice_text"):
            assert state.get(section) == {}

    def test_update_and_get(self, state):
        state.update("weather", {"temperature": 72})
        assert state.get("weather") == {"temperature": 72}

    def test_get_returns_copy(self, state):
        state.update("weather", {"temperature": 72})
        got = state.get("weather")
        got["temperature"] = 99
        assert state.get("weather")["temperature"] == 72

    def test_observer_notified(self, state):
        calls = []
        state.subscribe(lambda section, value: calls.append((section, value)))
        state.update("status", {"status": "reading"})
        assert len(calls) == 1
        assert calls[0] == ("status", {"status": "reading"})

    def test_observer_not_notified_when_disabled(self, state):
        calls = []
        state.subscribe(lambda s, v: calls.append(1))
        state.update("status", {"status": "reading"}, notify=False)
        assert len(calls) == 0

    def test_unsubscribe(self, state):
        calls = []
        unsub = state.subscribe(lambda s, v: calls.append(1))
        state.update("status", {"status": "a"})
        unsub()
        state.update("status", {"status": "b"})
        assert len(calls) == 1

    def test_get_all_returns_copy(self, state):
        state.update("weather", {"temp": 72})
        all_state = state.get_all()
        all_state["weather"]["temp"] = 99
        assert state.get("weather")["temp"] == 72

    def test_batch_update(self, state):
        calls = []
        state.subscribe(lambda s, v: calls.append(s))
        state.batch_update({
            "weather": {"temp": 72},
            "time": {"timestamp": "2024-01-01"},
        })
        assert state.get("weather") == {"temp": 72}
        assert state.get("time") == {"timestamp": "2024-01-01"}
        assert set(calls) == {"weather", "time"}

    def test_status_lock_blocks_updates(self, state):
        state.update("status", {"status": "idle"})
        state.lock_status()
        state.update("status", {"status": "reading"})
        assert state.get("status")["status"] == "idle"

    def test_status_lock_allows_force(self, state):
        state.update("status", {"status": "idle"})
        state.lock_status()
        state.update("status", {"status": "activated"}, force=True)
        assert state.get("status")["status"] == "activated"

    def test_status_unlock_restores(self, state):
        state.update("status", {"status": "reading"})
        state.lock_status()
        state.update("status", {"status": "writing"}, force=True)
        state.unlock_status()
        assert state.get("status")["status"] == "reading"

    def test_failed_observer_doesnt_block_others(self, state):
        results = []

        def bad_observer(s, v):
            raise RuntimeError("boom")

        def good_observer(s, v):
            results.append(v)

        state.subscribe(bad_observer)
        state.subscribe(good_observer)
        state.update("status", {"status": "idle"})
        assert len(results) == 1


# ── SessionTracker ──────────────────────────────────────────────────

class TestSessionTracker:
    def test_get_creates_session(self, session_tracker):
        session = session_tracker.get("sess-1")
        assert session["last_status"] == "idle"
        assert session["status_history"] == []

    def test_update_tracks_status_history(self, session_tracker):
        session_tracker.update("sess-1", "reading", 10.0, "Read")
        session_tracker.update("sess-1", "writing", 20.0, "Edit")
        session = session_tracker.get("sess-1")
        assert session["status_history"] == ["reading", "writing"]

    def test_update_deduplicates_consecutive_status(self, session_tracker):
        session_tracker.update("sess-1", "reading", 10.0, "Read")
        session_tracker.update("sess-1", "reading", 15.0, "Grep")
        session = session_tracker.get("sess-1")
        assert session["status_history"] == ["reading"]

    def test_update_caps_history_size(self, session_tracker):
        for i in range(30):
            session_tracker.update("sess-1", f"status-{i}", float(i), "Read")
        session = session_tracker.get("sess-1")
        assert len(session["status_history"]) == SessionTracker.HISTORY_SIZE
        assert len(session["context_history"]) == SessionTracker.HISTORY_SIZE

    def test_update_tracks_tool_outcomes(self, session_tracker):
        session_tracker.update("sess-1", "reading", 10.0, "Read", tool_succeeded=True)
        session_tracker.update("sess-1", "writing", 20.0, "Edit", tool_succeeded=False)
        session = session_tracker.get("sess-1")
        assert len(session["tool_outcomes"]) == 2
        assert session["tool_outcomes"][0] == {"tool": "Read", "succeeded": True}
        assert session["tool_outcomes"][1] == {"tool": "Edit", "succeeded": False}

    def test_get_last_context(self, session_tracker):
        session_tracker.update("sess-1", "reading", 42.5, "Read")
        assert session_tracker.get_last_context("sess-1") == 42.5

    def test_get_last_context_unknown_session(self, session_tracker):
        assert session_tracker.get_last_context("nonexistent") == 0.0

    def test_displayed_id_set_on_first_update(self, session_tracker):
        assert session_tracker.displayed_id is None
        session_tracker.update("sess-1", "reading", 10.0)
        assert session_tracker.displayed_id == "sess-1"

    def test_cleanup_stale(self, state, session_tracker):
        # Create a session with old last_seen
        sessions = {
            "old": {"last_seen": time.time() - 600, "status_history": [], "context_history": []},
            "new": {"last_seen": time.time(), "status_history": [], "context_history": []},
        }
        state.update("sessions", sessions)
        session_tracker.displayed_id = "old"
        session_tracker.cleanup_stale()
        remaining = state.get("sessions")
        assert "old" not in remaining
        assert "new" in remaining
        assert session_tracker.displayed_id == "new"


# ── classify_tool ───────────────────────────────────────────────────

class TestClassifyTool:
    @pytest.mark.parametrize("tool", sorted(READING_TOOLS))
    def test_reading_tools(self, tool):
        assert classify_tool(tool) == "reading"

    @pytest.mark.parametrize("tool", sorted(WRITING_TOOLS))
    def test_writing_tools(self, tool):
        assert classify_tool(tool) == "writing"

    @pytest.mark.parametrize("tool", sorted(EXECUTING_TOOLS))
    def test_executing_tools(self, tool):
        assert classify_tool(tool) == "executing"

    @pytest.mark.parametrize("tool", sorted(THINKING_TOOLS))
    def test_thinking_tools(self, tool):
        assert classify_tool(tool) == "thinking"

    @pytest.mark.parametrize("tool", sorted(AWAITING_TOOLS))
    def test_awaiting_tools(self, tool):
        assert classify_tool(tool) == "awaiting"

    def test_unknown_tool_returns_running(self):
        assert classify_tool("SomeUnknownTool") == "running"

    def test_mcp_writing_tool(self):
        assert classify_tool("mcp__serena__create_text_file") == "writing"

    def test_mcp_reading_tool(self):
        assert classify_tool("mcp__serena__read_file") == "reading"

    def test_mcp_executing_tool(self):
        assert classify_tool("mcp__playwright__browser_click") == "executing"

    def test_mcp_unknown_returns_running(self):
        assert classify_tool("mcp__foo__bar_baz") == "running"

    def test_returns_str_not_tuple(self):
        result = classify_tool("Read")
        assert isinstance(result, str)


# ── StatusColors ────────────────────────────────────────────────────

class TestStatusColors:
    def test_known_statuses_have_colors(self):
        for status in ("idle", "reading", "writing", "executing", "thinking", "awaiting"):
            color = StatusColors.get(status)
            assert isinstance(color, ColorDef)
            assert isinstance(color.ansi, int)
            assert isinstance(color.rgb, tuple)
            assert len(color.rgb) == 3

    def test_unknown_status_returns_fallback(self):
        color = StatusColors.get("nonexistent_status")
        assert isinstance(color, ColorDef)

    def test_status_map_is_dict(self):
        assert isinstance(STATUS_MAP, dict)
        assert len(STATUS_MAP) > 0
