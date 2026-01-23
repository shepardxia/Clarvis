"""Tests for MCP server tools."""

import pytest
from unittest.mock import patch

# Patch target - must patch where it's used, not where it's defined
PATCH_HUB_DATA = "central_hub.server.read_hub_data"


class TestGetClarvisState:
    """Tests for get_clarvis_state tool."""

    @pytest.mark.asyncio
    async def test_returns_full_state(self):
        """Should return complete Clarvis state with full history."""
        from central_hub.server import get_clarvis_state

        mock_hub_data = {
            "status": {
                "session_id": "test-session-123",
                "status": "thinking",
                "color": "yellow",
                "context_percent": 45.5,
                "status_history": ["idle", "thinking"],
                "context_history": [10, 45.5],
            },
            "weather": {
                "description": "Partly cloudy",
                "temperature": 68,
                "intensity": 0.3,
                "city": "San Francisco",
            },
            "time": {"timestamp": "2025-01-23T10:30:00"},
            "sessions": {
                "session-1": {"last_status": "idle", "status_history": ["idle"]},
                "session-2": {"last_status": "running", "status_history": ["running"]},
            },
            "updated_at": "2025-01-23T10:30:00",
        }

        with patch(PATCH_HUB_DATA, return_value=mock_hub_data):
            result = await get_clarvis_state()

        assert result["displayed_session"] == "test-session-123"
        assert result["status"] == "thinking"
        assert result["color"] == "yellow"
        assert result["context_percent"] == 45.5
        assert result["weather"]["temperature"] == 68
        assert len(result["sessions"]) == 2
        assert "session-1" in result["sessions"]

    @pytest.mark.asyncio
    async def test_handles_empty_data(self):
        """Should handle missing data gracefully."""
        from central_hub.server import get_clarvis_state

        with patch(PATCH_HUB_DATA, return_value={}):
            result = await get_clarvis_state()

        assert result["status"] == "unknown"
        assert result["sessions"] == {}

    @pytest.mark.asyncio
    async def test_handles_error(self):
        """Should return error dict on exception."""
        from central_hub.server import get_clarvis_state

        with patch(PATCH_HUB_DATA, side_effect=Exception("Test error")):
            result = await get_clarvis_state()

        assert "error" in result


class TestListClarvisSessions:
    """Tests for list_clarvis_sessions tool."""

    @pytest.mark.asyncio
    async def test_lists_all_sessions(self):
        """Should list all tracked sessions."""
        from central_hub.server import list_clarvis_sessions

        mock_hub_data = {
            "status": {"session_id": "session-1"},
            "sessions": {
                "session-1": {
                    "last_status": "running",
                    "last_context": 30.0,
                    "status_history": ["idle", "thinking", "running"],
                    "context_history": [10, 20, 30],
                },
                "session-2": {
                    "last_status": "idle",
                    "last_context": 50.0,
                    "status_history": ["idle"],
                    "context_history": [50],
                },
            },
        }

        with patch(PATCH_HUB_DATA, return_value=mock_hub_data):
            result = await list_clarvis_sessions()

        assert len(result) == 2

        session_1 = next(s for s in result if s["session_id"] == "session-1")
        assert session_1["is_displayed"] is True
        assert session_1["last_status"] == "running"
        assert session_1["status_history_length"] == 3

        session_2 = next(s for s in result if s["session_id"] == "session-2")
        assert session_2["is_displayed"] is False

    @pytest.mark.asyncio
    async def test_empty_sessions(self):
        """Should return message when no sessions tracked."""
        from central_hub.server import list_clarvis_sessions

        with patch(PATCH_HUB_DATA, return_value={}):
            result = await list_clarvis_sessions()

        assert result[0].get("message") == "No sessions tracked"


class TestGetClarvisSession:
    """Tests for get_clarvis_session tool."""

    @pytest.mark.asyncio
    async def test_returns_session_details(self):
        """Should return full session details."""
        from central_hub.server import get_clarvis_session

        mock_hub_data = {
            "status": {"session_id": "session-1"},
            "sessions": {
                "session-1": {
                    "last_status": "thinking",
                    "last_context": 42.0,
                    "status_history": ["idle", "thinking"],
                    "context_history": [10, 42],
                },
            },
        }

        with patch(PATCH_HUB_DATA, return_value=mock_hub_data):
            result = await get_clarvis_session("session-1")

        assert result["session_id"] == "session-1"
        assert result["is_displayed"] is True
        assert result["last_status"] == "thinking"
        assert result["last_context"] == 42.0
        assert result["status_history"] == ["idle", "thinking"]
        assert result["context_history"] == [10, 42]

    @pytest.mark.asyncio
    async def test_session_not_found(self):
        """Should return error for unknown session."""
        from central_hub.server import get_clarvis_session

        with patch(PATCH_HUB_DATA, return_value={"sessions": {}}):
            result = await get_clarvis_session("nonexistent")

        assert "error" in result
        assert "not found" in result["error"]


class TestGetClaudeStatus:
    """Tests for get_claude_status tool."""

    @pytest.mark.asyncio
    async def test_returns_status_string(self):
        """Should return formatted status string."""
        from central_hub.server import get_claude_status

        mock_hub_data = {
            "status": {
                "status": "running",
                "color": "green",
                "context_percent": 25.5,
            },
        }

        with patch(PATCH_HUB_DATA, return_value=mock_hub_data):
            result = await get_claude_status()

        assert "running" in result
        assert "green" in result
        assert "25.5%" in result

    @pytest.mark.asyncio
    async def test_no_status_data(self):
        """Should handle missing status data."""
        from central_hub.server import get_claude_status

        with patch(PATCH_HUB_DATA, return_value={}):
            result = await get_claude_status()

        assert "No status data found" in result
