"""In-memory MCP server tests using FastMCP 2.x Client.

Tests the full tool surface through the MCP protocol without subprocess or network.
Dependencies (daemon client, SpotifySession) are mocked via create_app() factory.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from fastmcp import Client

from clarvis.server import create_app


# --- Fixtures ---

@pytest.fixture
def mock_daemon():
    """Mock DaemonClient that routes by method name."""
    client = MagicMock()
    client.is_daemon_running.return_value = True

    def route_call(method, **kwargs):
        if method == "ping":
            return "pong"
        if method == "refresh_time":
            return {"timestamp": "2026-02-06T12:00:00", "timezone": "America/New_York"}
        if method == "get_weather":
            return {
                "temperature": 32,
                "description": "clear",
                "wind_speed": 10,
                "city": "Boston",
            }
        if method == "refresh_weather":
            return {
                "temperature": 32,
                "description": "clear",
                "wind_speed": 10,
                "city": "Boston",
            }
        if method == "get_token_usage":
            return {"5h": {"used": 1000, "limit": 5000}, "7d": {"used": 3000, "limit": 25000}}
        return None

    client.call.side_effect = route_call
    return client


@pytest.fixture
def mock_spotify_session():
    """Mock SpotifySession with device list for get devices."""
    session = MagicMock()

    # Mock device objects
    device_a = MagicMock()
    device_a.name = "Den"
    device_b = MagicMock()
    device_b.name = "Kitchen"
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

    app = create_app(
        daemon_client=mock_daemon,
        get_session=lambda: mock_spotify_session,
    )
    async with Client(app) as c:
        yield c


# --- Tool Discovery ---

@pytest.mark.asyncio
async def test_all_tools_registered(mcp_client):
    """All tools should be accessible through the MCP protocol."""
    tools = await mcp_client.list_tools()
    names = {t.name for t in tools}

    # Daemon tools
    assert {"ping", "get_weather", "get_time", "get_token_usage", "get_music_context"} <= names
    # Session tools
    assert {"list_active_sessions", "get_session_thoughts", "get_latest_thought"} <= names
    # Music tool (mounted DSL sub-server)
    assert "spotify" in names


@pytest.mark.asyncio
async def test_ctx_not_in_schemas(mcp_client):
    """Context parameter should not appear in any tool's input schema."""
    tools = await mcp_client.list_tools()
    for tool in tools:
        props = tool.inputSchema.get("properties", {})
        assert "ctx" not in props, f"ctx leaked into schema for {tool.name}"


# --- Daemon Tools ---

@pytest.mark.asyncio
async def test_ping(mcp_client, mock_daemon):
    result = await mcp_client.call_tool("ping", {})
    assert result.data == "pong"
    mock_daemon.call.assert_any_call("ping")


@pytest.mark.asyncio
async def test_get_weather(mcp_client):
    result = await mcp_client.call_tool("get_weather", {})
    assert "32" in result.data
    assert "Boston" in result.data


@pytest.mark.asyncio
async def test_get_time(mcp_client):
    result = await mcp_client.call_tool("get_time", {})
    assert "2026" in result.data
    assert "New_York" in result.data


@pytest.mark.asyncio
async def test_get_time_with_timezone(mcp_client, mock_daemon):
    await mcp_client.call_tool("get_time", {"timezone": "US/Pacific"})
    mock_daemon.call.assert_any_call("refresh_time", timezone="US/Pacific")


@pytest.mark.asyncio
async def test_get_token_usage(mcp_client):
    result = await mcp_client.call_tool("get_token_usage", {})
    data = json.loads(result.data)
    assert data["5h"]["used"] == 1000


# --- Spotify DSL Tools ---

@pytest.mark.asyncio
async def test_spotify_play(mcp_client, mock_spotify_session):
    """Spotify tool executes commands and includes device list."""
    result = await mcp_client.call_tool("spotify", {"command": 'play "jazz"'})
    assert result.data["status"] == "ok"
    assert result.data["available_devices"] == ["Den", "Kitchen"]


@pytest.mark.asyncio
async def test_spotify_devices_cached_across_calls(mcp_client, mock_spotify_session):
    """Device list is fetched once and cached for subsequent calls."""
    await mcp_client.call_tool("spotify", {"command": "now playing"})
    await mcp_client.call_tool("spotify", {"command": "pause"})

    # "get devices" called once (first invocation), then cached
    device_calls = [c for c in mock_spotify_session.run.call_args_list if c.args[0] == "get devices"]
    assert len(device_calls) == 1


# --- Error Handling ---

@pytest.mark.asyncio
async def test_ping_daemon_not_running(mock_spotify_session):
    """When daemon isn't running, tools should return error messages, not crash."""
    dead_daemon = MagicMock()
    dead_daemon.is_daemon_running.return_value = False

    import clarvis.spotify_tools as st
    st._device_cache.update({"names": None, "ts": 0})

    app = create_app(
        daemon_client=dead_daemon,
        get_session=lambda: mock_spotify_session,
    )
    async with Client(app) as c:
        result = await c.call_tool("ping", {})
        assert "not running" in result.data


@pytest.mark.asyncio
async def test_spotify_tool_error(mock_daemon):
    """When session throws, spotify tool returns error dict."""
    broken_session = MagicMock()
    broken_session.run.side_effect = Exception("Connection failed")

    import clarvis.spotify_tools as st
    st._device_cache.update({"names": None, "ts": 0})

    app = create_app(
        daemon_client=mock_daemon,
        get_session=lambda: broken_session,
    )
    async with Client(app) as c:
        result = await c.call_tool("spotify", {"command": "now playing"})
        assert "error" in result.data
        assert "Connection failed" in result.data["error"]


@pytest.mark.asyncio
async def test_no_clautify_tools(mcp_client):
    """Old clautify tools (now_playing, play, pause, etc.) should not exist."""
    tool_names = {t.name for t in await mcp_client.list_tools()}
    assert "spotify" in tool_names
    assert "now_playing" not in tool_names
    assert "play" not in tool_names
    assert "search_and_play" not in tool_names
