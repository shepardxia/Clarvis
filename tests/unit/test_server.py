"""In-memory MCP server tests using FastMCP 2.x Client.

Tests the full tool surface through the MCP protocol without subprocess or network.
Dependencies (daemon, SpotifySession) are mocked via create_app() factory.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastmcp import Client

from clarvis.server import create_app

# --- Fixtures ---


@pytest.fixture
def mock_daemon():
    """Mock daemon object with state, refresh, and services."""
    daemon = MagicMock()

    # state.get() returns weather dict
    daemon.state.get.side_effect = lambda key, default=None: {
        "weather": {"temperature": 32, "description": "clear", "wind_speed": 10, "city": "Boston"},
    }.get(key, default)

    # refresh manager
    daemon.refresh.refresh_weather.return_value = {
        "temperature": 32,
        "description": "clear",
        "wind_speed": 10,
        "city": "Boston",
    }
    daemon.refresh.refresh_time.return_value = {
        "timestamp": "2026-02-06T12:00:00",
        "timezone": "America/New_York",
    }

    # token usage
    daemon.token_usage_service = MagicMock()
    daemon.token_usage_service.get_usage.return_value = {
        "5h": {"used": 1000, "limit": 5000},
        "7d": {"used": 3000, "limit": 25000},
    }

    # memory service (async methods)
    daemon.memory_service = MagicMock()
    daemon.memory_service._ready = True
    daemon.memory_service.add = AsyncMock(return_value={"status": "ok", "dataset": "shepard", "bytes": 10})
    daemon.memory_service.search = AsyncMock(return_value=[{"result": "test"}])
    daemon.memory_service.cognify = AsyncMock(return_value={"status": "ok", "dataset": "shepard"})
    daemon.memory_service.status = AsyncMock(return_value={"ready": True})

    # context accumulator
    daemon.context_accumulator = MagicMock()
    daemon.context_accumulator.get_pending.return_value = {
        "sessions_since_last": [],
        "staged_items": [],
        "last_check_in": "2026-02-06T12:00:00+00:00",
    }

    return daemon


@pytest.fixture
def mock_spotify_session():
    """Mock SpotifySession with device list."""
    session = MagicMock()
    device_a, device_b = MagicMock(), MagicMock()
    device_a.name, device_b.name = "Den", "Kitchen"
    devices_obj = MagicMock()
    devices_obj.devices = {"a": device_a, "b": device_b}

    def route_run(command):
        if command == "get devices":
            return {"status": "ok", "query": "get_devices", "data": devices_obj}
        return {"status": "ok"}

    session.run.side_effect = route_run
    return session


@pytest_asyncio.fixture
async def mcp_client(mock_daemon, mock_spotify_session):
    """In-memory MCP client connected to a test app with mocked deps."""
    import clarvis.spotify_tools as st

    st._device_cache.update({"names": None, "ts": 0})
    app = create_app(daemon=mock_daemon, get_session=lambda: mock_spotify_session)
    async with Client(app) as c:
        yield c


# --- Tool surface ---


@pytest.mark.asyncio
async def test_tool_surface(mcp_client):
    """All expected tools registered, no leaked params, no legacy tools."""
    tools = await mcp_client.list_tools()
    names = {t.name for t in tools}

    # Core tools present
    assert {"ping", "get_context", "continue_listening"} <= names
    assert "spotify" in names

    # Memory tools present
    assert {"memory_add", "memory_search", "memory_cognify", "memory_status", "check_in"} <= names

    # Unregistered tools not exposed
    for unregistered in (
        "get_weather",
        "get_time",
        "get_token_usage",
        "list_active_sessions",
        "get_session_thoughts",
        "get_latest_thought",
    ):
        assert unregistered not in names

    # Legacy tools gone
    for legacy in ("now_playing", "play", "search_and_play"):
        assert legacy not in names

    # ctx not leaked into any schema
    for tool in tools:
        assert "ctx" not in tool.inputSchema.get("properties", {}), f"ctx leaked in {tool.name}"


# --- Daemon tools ---


@pytest.mark.asyncio
async def test_ping(mcp_client):
    result = await mcp_client.call_tool("ping", {})
    assert result.data == "pong"


# --- Memory tools ---


@pytest.mark.asyncio
async def test_memory_add(mcp_client, mock_daemon):
    result = await mcp_client.call_tool("memory_add", {"data": "test fact"})
    data = json.loads(result.content[0].text)
    assert data["status"] == "ok"
    mock_daemon.memory_service.add.assert_awaited_once_with("test fact", "shepard")


@pytest.mark.asyncio
async def test_memory_search(mcp_client, mock_daemon):
    result = await mcp_client.call_tool("memory_search", {"query": "test query"})
    data = json.loads(result.content[0].text)
    assert data[0]["result"] == "test"
    mock_daemon.memory_service.search.assert_awaited_once_with("test query", "GRAPH_COMPLETION", 10, datasets=None)


@pytest.mark.asyncio
async def test_memory_cognify(mcp_client, mock_daemon):
    result = await mcp_client.call_tool("memory_cognify", {})
    data = json.loads(result.content[0].text)
    assert data["status"] == "ok"
    mock_daemon.memory_service.cognify.assert_awaited_once_with("shepard")


@pytest.mark.asyncio
async def test_memory_status(mcp_client, mock_daemon):
    result = await mcp_client.call_tool("memory_status", {})
    data = json.loads(result.content[0].text)
    assert data["ready"] is True


@pytest.mark.asyncio
async def test_check_in(mcp_client, mock_daemon):
    result = await mcp_client.call_tool("check_in", {})
    data = json.loads(result.content[0].text)
    assert "sessions_since_last" in data
    assert "relevant_memories" in data


# --- Spotify ---


@pytest.mark.asyncio
async def test_spotify_play_and_device_cache(mcp_client, mock_spotify_session):
    """Spotify executes commands, includes device list, and caches devices."""
    result = await mcp_client.call_tool("spotify", {"command": 'play "jazz"'})
    assert "Den" in result.data and "Kitchen" in result.data

    # Second call should use cached devices
    await mcp_client.call_tool("spotify", {"command": "pause"})
    device_calls = [c for c in mock_spotify_session.run.call_args_list if c.args[0] == "get devices"]
    assert len(device_calls) == 1


# --- Error handling ---


@pytest.mark.asyncio
async def test_spotify_session_error(mock_daemon):
    broken = MagicMock()
    broken.run.side_effect = Exception("Connection failed")

    import clarvis.spotify_tools as st

    st._device_cache.update({"names": None, "ts": 0})
    app = create_app(daemon=mock_daemon, get_session=lambda: broken)
    async with Client(app) as c:
        result = await c.call_tool("spotify", {"command": "now playing"})
        assert "Connection failed" in result.data
