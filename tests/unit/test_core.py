"""Tests for core modules: StateStore, SessionTracker, tool_classifier, colors."""

import time

import pytest

from clarvis.core.colors import STATUS_MAP, ColorDef, StatusColors
from clarvis.core.session_tracker import SessionTracker
from clarvis.core.tool_classifier import classify_tool

# ── StateStore ──────────────────────────────────────────────────────


class TestStateStore:
    def test_initial_sections_empty(self, state):
        for section in ("status", "sessions", "weather", "location", "time", "voice_text"):
            assert state.get(section) == {}

    def test_update_get_returns_copy(self, state):
        state.update("weather", {"temperature": 72})
        assert state.get("weather") == {"temperature": 72}
        # Mutating returned dict doesn't affect store
        state.get("weather")["temperature"] = 99
        assert state.get("weather")["temperature"] == 72

    def test_observer_lifecycle(self, state):
        calls = []
        unsub = state.subscribe(lambda s, v: calls.append((s, v)))

        state.update("status", {"status": "reading"})
        assert calls == [("status", {"status": "reading"})]

        state.update("status", {"status": "writing"}, notify=False)
        assert len(calls) == 1  # no notification

        unsub()
        state.update("status", {"status": "idle"})
        assert len(calls) == 1  # unsubscribed

    def test_batch_update(self, state):
        calls = []
        state.subscribe(lambda s, v: calls.append(s))
        state.batch_update({"weather": {"temp": 72}, "time": {"timestamp": "2024-01-01"}})
        assert state.get("weather") == {"temp": 72}
        assert state.get("time") == {"timestamp": "2024-01-01"}
        assert set(calls) == {"weather", "time"}

    def test_status_lock(self, state):
        state.update("status", {"status": "idle"})
        state.lock_status()
        # Normal update blocked
        state.update("status", {"status": "reading"})
        assert state.get("status")["status"] == "idle"
        # Force bypasses lock
        state.update("status", {"status": "activated"}, force=True)
        assert state.get("status")["status"] == "activated"
        # Unlock restores pre-lock status
        state.unlock_status()
        assert state.get("status")["status"] == "idle"

    def test_failed_observer_doesnt_block_others(self, state):
        results = []
        state.subscribe(lambda s, v: (_ for _ in ()).throw(RuntimeError("boom")))
        state.subscribe(lambda s, v: results.append(v))
        state.update("status", {"status": "idle"})
        assert len(results) == 1

    def test_get_all_returns_copy(self, state):
        state.update("weather", {"temp": 72})
        all_state = state.get_all()
        all_state["weather"]["temp"] = 99
        assert state.get("weather")["temp"] == 72


# ── SessionTracker ──────────────────────────────────────────────────


class TestSessionTracker:
    def test_get_creates_session(self, session_tracker):
        session = session_tracker.get("sess-1")
        assert session["last_status"] == "idle"
        assert session["status_history"] == []

    def test_update_tracks_history(self, session_tracker):
        session_tracker.update("sess-1", "reading", 10.0, "Read")
        session_tracker.update("sess-1", "writing", 20.0, "Edit")
        session = session_tracker.get("sess-1")
        assert session["status_history"] == ["reading", "writing"]

        # Consecutive duplicates are deduplicated
        session_tracker.update("sess-1", "writing", 25.0, "Edit")
        assert session_tracker.get("sess-1")["status_history"] == ["reading", "writing"]

        # History capped at HISTORY_SIZE
        for i in range(30):
            session_tracker.update("sess-1", f"s{i}", float(i), "Read")
        session = session_tracker.get("sess-1")
        assert len(session["status_history"]) == SessionTracker.HISTORY_SIZE
        assert len(session["context_history"]) == SessionTracker.HISTORY_SIZE

    def test_tool_outcomes(self, session_tracker):
        session_tracker.update("sess-1", "reading", 10.0, "Read", tool_succeeded=True)
        session_tracker.update("sess-1", "writing", 20.0, "Edit", tool_succeeded=False)
        outcomes = session_tracker.get("sess-1")["tool_outcomes"]
        assert outcomes == [
            {"tool": "Read", "succeeded": True},
            {"tool": "Edit", "succeeded": False},
        ]

    def test_displayed_id_and_last_context(self, session_tracker):
        assert session_tracker.displayed_id is None
        session_tracker.update("sess-1", "reading", 42.5)
        assert session_tracker.displayed_id == "sess-1"
        assert session_tracker.get_last_context("sess-1") == 42.5
        assert session_tracker.get_last_context("nonexistent") == 0.0

    def test_cleanup_stale(self, state, session_tracker):
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
    @pytest.mark.parametrize(
        "tool, expected",
        [
            ("Read", "reading"),
            ("Edit", "writing"),
            ("Bash", "executing"),
            ("Task", "thinking"),
            ("AskUserQuestion", "awaiting"),
            ("SomeUnknownTool", "running"),
        ],
    )
    def test_known_categories(self, tool, expected):
        assert classify_tool(tool) == expected

    @pytest.mark.parametrize(
        "tool, expected",
        [
            ("mcp__serena__create_text_file", "writing"),
            ("mcp__serena__read_file", "reading"),
            ("mcp__playwright__browser_click", "executing"),
            ("mcp__foo__bar_baz", "running"),
        ],
    )
    def test_mcp_heuristic(self, tool, expected):
        assert classify_tool(tool) == expected


# ── StatusColors ────────────────────────────────────────────────────


def test_status_colors():
    assert isinstance(STATUS_MAP, dict) and len(STATUS_MAP) > 0

    for status in ("idle", "reading", "writing", "executing", "thinking", "awaiting"):
        color = StatusColors.get(status)
        assert isinstance(color, ColorDef)
        assert isinstance(color.ansi, int)
        assert isinstance(color.rgb, tuple) and len(color.rgb) == 3

    # Unknown returns fallback
    assert isinstance(StatusColors.get("nonexistent"), ColorDef)
