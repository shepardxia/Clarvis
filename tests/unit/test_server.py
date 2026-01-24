"""Tests for MCP server tools."""

import pytest
from unittest.mock import patch, MagicMock

# Patch the daemon client
PATCH_CLIENT = "clarvis.server.get_daemon_client"


def make_mock_client(call_returns=None, is_running=True):
    """Create a mock daemon client with specified return values."""
    client = MagicMock()
    client.is_daemon_running.return_value = is_running

    if call_returns is not None:
        client.call.side_effect = lambda method, **kwargs: call_returns.get(method, {})

    return client


class TestGetClarvisState:
    """Tests for get_clarvis_state tool."""

    @pytest.mark.asyncio
    async def test_returns_full_state(self):
        """Should return complete Clarvis state with full history."""
        from clarvis.server import get_clarvis_state

        mock_state = {
            "displayed_session": "test-session-123",
            "status": "thinking",
            "color": "yellow",
            "context_percent": 45.5,
            "status_history": ["idle", "thinking"],
            "context_history": [10, 45.5],
            "weather": {
                "type": "Partly cloudy",
                "temperature": 68,
                "intensity": 0.3,
                "city": "San Francisco",
            },
            "time": "2025-01-23T10:30:00",
            "sessions": {
                "session-1": {"last_status": "idle", "status_history": ["idle"]},
                "session-2": {"last_status": "running", "status_history": ["running"]},
            },
        }

        mock_client = make_mock_client({"get_state": mock_state})
        with patch(PATCH_CLIENT, return_value=mock_client):
            result = await get_clarvis_state()

        assert result["displayed_session"] == "test-session-123"
        assert result["status"] == "thinking"
        assert result["color"] == "yellow"
        assert result["context_percent"] == 45.5
        assert result["weather"]["temperature"] == 68
        assert len(result["sessions"]) == 2

    @pytest.mark.asyncio
    async def test_handles_empty_data(self):
        """Should handle missing data gracefully."""
        from clarvis.server import get_clarvis_state

        mock_state = {
            "displayed_session": None,
            "status": "unknown",
            "color": "gray",
            "context_percent": 0,
            "status_history": [],
            "context_history": [],
            "weather": {},
            "time": None,
            "sessions": {},
        }

        mock_client = make_mock_client({"get_state": mock_state})
        with patch(PATCH_CLIENT, return_value=mock_client):
            result = await get_clarvis_state()

        assert result["status"] == "unknown"
        assert result["sessions"] == {}

    @pytest.mark.asyncio
    async def test_handles_daemon_not_running(self):
        """Should return error when daemon not running."""
        from clarvis.server import get_clarvis_state

        mock_client = make_mock_client(is_running=False)
        with patch(PATCH_CLIENT, return_value=mock_client):
            result = await get_clarvis_state()

        assert "error" in result
        assert "daemon" in result["error"].lower()


class TestListClarvisSessions:
    """Tests for list_clarvis_sessions tool."""

    @pytest.mark.asyncio
    async def test_lists_all_sessions(self):
        """Should list all tracked sessions."""
        from clarvis.server import list_clarvis_sessions

        mock_sessions = [
            {
                "session_id": "session-1",
                "is_displayed": True,
                "last_status": "running",
                "last_context": 30.0,
                "status_history_length": 3,
                "context_history_length": 3,
            },
            {
                "session_id": "session-2",
                "is_displayed": False,
                "last_status": "idle",
                "last_context": 50.0,
                "status_history_length": 1,
                "context_history_length": 1,
            },
        ]

        mock_client = make_mock_client({"get_sessions": mock_sessions})
        with patch(PATCH_CLIENT, return_value=mock_client):
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
        from clarvis.server import list_clarvis_sessions

        mock_client = make_mock_client({"get_sessions": []})
        with patch(PATCH_CLIENT, return_value=mock_client):
            result = await list_clarvis_sessions()

        assert result[0].get("message") == "No sessions tracked"


class TestGetClarvisSession:
    """Tests for get_clarvis_session tool."""

    @pytest.mark.asyncio
    async def test_returns_session_details(self):
        """Should return full session details."""
        from clarvis.server import get_clarvis_session

        mock_session = {
            "session_id": "session-1",
            "is_displayed": True,
            "last_status": "thinking",
            "last_context": 42.0,
            "status_history": ["idle", "thinking"],
            "context_history": [10, 42],
        }

        mock_client = make_mock_client({"get_session": mock_session})
        with patch(PATCH_CLIENT, return_value=mock_client):
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
        from clarvis.server import get_clarvis_session

        mock_client = MagicMock()
        mock_client.is_daemon_running.return_value = True
        mock_client.call.side_effect = RuntimeError("Session nonexistent not found")

        with patch(PATCH_CLIENT, return_value=mock_client):
            result = await get_clarvis_session("nonexistent")

        assert "error" in result
        assert "not found" in result["error"]


class TestGetClaudeStatus:
    """Tests for get_claude_status tool."""

    @pytest.mark.asyncio
    async def test_returns_status_string(self):
        """Should return formatted status string."""
        from clarvis.server import get_claude_status

        mock_status = {
            "status": "running",
            "color": "green",
            "context_percent": 25.5,
        }

        mock_client = make_mock_client({"get_status": mock_status})
        with patch(PATCH_CLIENT, return_value=mock_client):
            result = await get_claude_status()

        assert "running" in result
        assert "green" in result
        assert "25.5%" in result

    @pytest.mark.asyncio
    async def test_no_status_data(self):
        """Should handle missing status data."""
        from clarvis.server import get_claude_status

        mock_client = make_mock_client({"get_status": {}})
        with patch(PATCH_CLIENT, return_value=mock_client):
            result = await get_claude_status()

        assert "No status data found" in result
