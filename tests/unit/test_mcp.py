"""MCP tool surface — standard port (:7777) tools only.

After the tool-layer redesign, only :7777 serves external Claude Code sessions.
Agent tools (memory, spotify, timers) are daemon IPC commands via ctools.
"""

from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from fastmcp import Client

from clarvis.mcp.server import create_app


@pytest.fixture
def mock_daemon(tmp_path):
    daemon = MagicMock()
    daemon.state.get.side_effect = lambda key, default=None: {
        "weather": {"temperature": 32, "description": "clear", "wind_speed": 10, "city": "Boston"},
    }.get(key, default)
    daemon.refresh.refresh_weather.return_value = {"temperature": 32, "description": "clear"}
    daemon.refresh.refresh_time.return_value = {"timestamp": "2026-02-06T12:00:00", "timezone": "America/New_York"}
    daemon.staging_dir = str(tmp_path / "staging")
    daemon.channel_manager = None
    return daemon


@pytest_asyncio.fixture
async def client(mock_daemon):
    app = create_app(mock_daemon)
    async with Client(app) as c:
        yield c


@pytest.mark.asyncio
async def test_standard_tools_registered(client):
    """Standard port has ping, get_context, stage_memory only."""
    tools = await client.list_tools()
    names = {t.name for t in tools}
    assert {"ping", "get_context", "stage_memory"} <= names
    # Agent-only tools must NOT be present
    assert "recall" not in names
    assert "remember" not in names
    assert "clautify" not in names
    assert "set_timer" not in names
    assert "reflect_complete" not in names
    assert "prompt_response" not in names


@pytest.mark.asyncio
async def test_ping(client):
    r = await client.call_tool("ping", {})
    assert "pong" in r.data.lower()
