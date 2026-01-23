"""Tests for daemon module."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from central_hub.daemon import CentralHubDaemon


class TestCentralHubDaemon:
    """Tests for CentralHubDaemon class."""

    def test_create_daemon(self, temp_hub_files):
        """Test daemon initialization."""
        daemon = CentralHubDaemon(
            status_raw_file=temp_hub_files["status_raw"],
            hub_data_file=temp_hub_files["hub_data"],
            output_file=temp_hub_files["widget_display"],
        )

        assert daemon.status_raw_file == temp_hub_files["status_raw"]
        # display_status depends on loaded data, check it's a valid status
        assert daemon.display_status in ["idle", "running", "thinking", "awaiting", "resting"]
        assert daemon.HISTORY_SIZE == 20

    def test_get_session_creates_new(self, temp_hub_files):
        """Test session creation on first access."""
        daemon = CentralHubDaemon(
            status_raw_file=temp_hub_files["status_raw"],
            hub_data_file=temp_hub_files["hub_data"],
            output_file=temp_hub_files["widget_display"],
        )

        session = daemon._get_session("new-session-id")

        assert "new-session-id" in daemon.sessions
        assert session["status_history"] == []
        assert session["context_history"] == []
        assert session["last_status"] == "idle"

    def test_get_session_returns_existing(self, temp_hub_files):
        """Test getting existing session."""
        daemon = CentralHubDaemon(
            status_raw_file=temp_hub_files["status_raw"],
            hub_data_file=temp_hub_files["hub_data"],
            output_file=temp_hub_files["widget_display"],
        )

        # Create session with some data via state store
        daemon.state.update("sessions", {
            "existing-session": {
                "status_history": ["idle", "running"],
                "context_history": [10, 20],
                "last_status": "running",
                "last_context": 20,
            }
        })

        session = daemon._get_session("existing-session")
        assert session["last_status"] == "running"
        assert session["last_context"] == 20


class TestProcessHookEvent:
    """Tests for hook event processing."""

    def test_pre_tool_use_sets_running(self, temp_hub_files, sample_hook_event):
        """PreToolUse should set status to running."""
        daemon = CentralHubDaemon(
            status_raw_file=temp_hub_files["status_raw"],
            hub_data_file=temp_hub_files["hub_data"],
            output_file=temp_hub_files["widget_display"],
        )

        result = daemon.process_hook_event(sample_hook_event)

        assert result["status"] == "running"
        assert result["color"] == "green"

    def test_post_tool_use_sets_thinking(self, temp_hub_files):
        """PostToolUse should set status to thinking."""
        daemon = CentralHubDaemon(
            status_raw_file=temp_hub_files["status_raw"],
            hub_data_file=temp_hub_files["hub_data"],
            output_file=temp_hub_files["widget_display"],
        )

        event = {
            "session_id": "test-session",
            "hook_event_name": "PostToolUse",
            "context_window": {"used_percentage": 30},
        }
        result = daemon.process_hook_event(event)

        assert result["status"] == "thinking"
        assert result["color"] == "yellow"

    def test_stop_sets_awaiting(self, temp_hub_files):
        """Stop should set status to awaiting."""
        daemon = CentralHubDaemon(
            status_raw_file=temp_hub_files["status_raw"],
            hub_data_file=temp_hub_files["hub_data"],
            output_file=temp_hub_files["widget_display"],
        )

        event = {
            "session_id": "test-session",
            "hook_event_name": "Stop",
            "context_window": {"used_percentage": 50},
        }
        result = daemon.process_hook_event(event)

        assert result["status"] == "awaiting"
        assert result["color"] == "blue"

    def test_user_prompt_submit_sets_thinking(self, temp_hub_files):
        """UserPromptSubmit should set status to thinking."""
        daemon = CentralHubDaemon(
            status_raw_file=temp_hub_files["status_raw"],
            hub_data_file=temp_hub_files["hub_data"],
            output_file=temp_hub_files["widget_display"],
        )

        event = {
            "session_id": "test-session",
            "hook_event_name": "UserPromptSubmit",
            "context_window": {"used_percentage": 15},
        }
        result = daemon.process_hook_event(event)

        assert result["status"] == "thinking"

    def test_context_percent_extracted(self, temp_hub_files, sample_hook_event):
        """Context percentage should be extracted from event."""
        daemon = CentralHubDaemon(
            status_raw_file=temp_hub_files["status_raw"],
            hub_data_file=temp_hub_files["hub_data"],
            output_file=temp_hub_files["widget_display"],
        )

        result = daemon.process_hook_event(sample_hook_event)

        assert result["context_percent"] == 45

    def test_session_id_extracted(self, temp_hub_files, sample_hook_event):
        """Session ID should be included in result."""
        daemon = CentralHubDaemon(
            status_raw_file=temp_hub_files["status_raw"],
            hub_data_file=temp_hub_files["hub_data"],
            output_file=temp_hub_files["widget_display"],
        )

        result = daemon.process_hook_event(sample_hook_event)

        assert result["session_id"] == "abc-123-def-456"


class TestHistoryTracking:
    """Tests for per-session history tracking."""

    def test_add_to_history(self, temp_hub_files):
        """Test adding entries to history."""
        daemon = CentralHubDaemon(
            status_raw_file=temp_hub_files["status_raw"],
            hub_data_file=temp_hub_files["hub_data"],
            output_file=temp_hub_files["widget_display"],
        )

        daemon._add_to_history("session-1", "running", 25.0)
        daemon._add_to_history("session-1", "thinking", 30.0)

        session = daemon.sessions["session-1"]
        assert session["status_history"] == ["running", "thinking"]
        assert session["context_history"] == [25.0, 30.0]

    def test_history_deduplicates_status(self, temp_hub_files):
        """Consecutive same statuses should not create duplicates."""
        daemon = CentralHubDaemon(
            status_raw_file=temp_hub_files["status_raw"],
            hub_data_file=temp_hub_files["hub_data"],
            output_file=temp_hub_files["widget_display"],
        )

        daemon._add_to_history("session-1", "running", 25.0)
        daemon._add_to_history("session-1", "running", 26.0)
        daemon._add_to_history("session-1", "running", 27.0)

        session = daemon.sessions["session-1"]
        assert session["status_history"] == ["running"]  # Only one entry
        assert len(session["context_history"]) == 3  # But context still tracked

    def test_history_max_size(self, temp_hub_files):
        """History should not exceed HISTORY_SIZE."""
        daemon = CentralHubDaemon(
            status_raw_file=temp_hub_files["status_raw"],
            hub_data_file=temp_hub_files["hub_data"],
            output_file=temp_hub_files["widget_display"],
        )

        # Add more than HISTORY_SIZE entries
        for i in range(30):
            # Alternate statuses to avoid deduplication
            status = "running" if i % 2 == 0 else "thinking"
            daemon._add_to_history("session-1", status, float(i))

        session = daemon.sessions["session-1"]
        assert len(session["status_history"]) <= daemon.HISTORY_SIZE
        assert len(session["context_history"]) <= daemon.HISTORY_SIZE

    def test_zero_context_not_added(self, temp_hub_files):
        """Zero context values should not be added to history."""
        daemon = CentralHubDaemon(
            status_raw_file=temp_hub_files["status_raw"],
            hub_data_file=temp_hub_files["hub_data"],
            output_file=temp_hub_files["widget_display"],
        )

        daemon._add_to_history("session-1", "running", 0)
        daemon._add_to_history("session-1", "thinking", 25.0)
        daemon._add_to_history("session-1", "running", 0)

        session = daemon.sessions["session-1"]
        assert session["context_history"] == [25.0]  # Only non-zero value

    def test_get_last_context(self, temp_hub_files):
        """Test getting last known context."""
        daemon = CentralHubDaemon(
            status_raw_file=temp_hub_files["status_raw"],
            hub_data_file=temp_hub_files["hub_data"],
            output_file=temp_hub_files["widget_display"],
        )

        daemon._add_to_history("session-1", "running", 25.0)
        daemon._add_to_history("session-1", "thinking", 30.0)

        assert daemon._get_last_context("session-1") == 30.0
        assert daemon._get_last_context("unknown-session") == 0.0

    def test_separate_sessions(self, temp_hub_files):
        """Different sessions should have separate histories."""
        daemon = CentralHubDaemon(
            status_raw_file=temp_hub_files["status_raw"],
            hub_data_file=temp_hub_files["hub_data"],
            output_file=temp_hub_files["widget_display"],
        )

        daemon._add_to_history("session-1", "running", 25.0)
        daemon._add_to_history("session-2", "thinking", 50.0)

        assert daemon.sessions["session-1"]["last_context"] == 25.0
        assert daemon.sessions["session-2"]["last_context"] == 50.0
        assert daemon.sessions["session-1"]["last_status"] == "running"
        assert daemon.sessions["session-2"]["last_status"] == "thinking"


class TestEventSequence:
    """Tests for processing event sequences."""

    def test_full_event_sequence(self, temp_hub_files, sample_hook_events):
        """Test processing a full sequence of events."""
        daemon = CentralHubDaemon(
            status_raw_file=temp_hub_files["status_raw"],
            hub_data_file=temp_hub_files["hub_data"],
            output_file=temp_hub_files["widget_display"],
        )

        results = []
        for event in sample_hook_events:
            result = daemon.process_hook_event(event)
            results.append(result)

        # Check final state
        assert results[-1]["status"] == "awaiting"  # Stop event
        assert results[-1]["context_percent"] == 30

        # Check history was tracked
        session = daemon.sessions["test-session-001"]
        assert "thinking" in session["status_history"]
        assert "running" in session["status_history"]
        assert "awaiting" in session["status_history"]
