"""In-memory MCP server tests using FastMCP 2.x Client.

Tests the full tool surface through the MCP protocol without subprocess or network.
Dependencies (daemon client, SpotifySession) are mocked via create_app() factory.
"""

import json
from unittest.mock import MagicMock

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
        routes = {
            "ping": "pong",
            "refresh_time": {"timestamp": "2026-02-06T12:00:00", "timezone": "America/New_York"},
            "get_weather": {"temperature": 32, "description": "clear", "wind_speed": 10, "city": "Boston"},
            "refresh_weather": {"temperature": 32, "description": "clear", "wind_speed": 10, "city": "Boston"},
            "get_token_usage": {"5h": {"used": 1000, "limit": 5000}, "7d": {"used": 3000, "limit": 25000}},
        }
        return routes.get(method)

    client.call.side_effect = route_call
    return client


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
    app = create_app(daemon_client=mock_daemon, get_session=lambda: mock_spotify_session)
    async with Client(app) as c:
        yield c


# --- Tool surface ---


@pytest.mark.asyncio
async def test_tool_surface(mcp_client):
    """All expected tools registered, no leaked params, no legacy tools."""
    tools = await mcp_client.list_tools()
    names = {t.name for t in tools}

    # Core tools present
    assert {"ping", "get_weather", "get_time", "get_token_usage", "get_music_context"} <= names
    assert {"list_active_sessions", "get_session_thoughts", "get_latest_thought"} <= names
    assert "spotify" in names

    # Legacy tools gone
    for legacy in ("now_playing", "play", "search_and_play"):
        assert legacy not in names

    # ctx not leaked into any schema
    for tool in tools:
        assert "ctx" not in tool.inputSchema.get("properties", {}), f"ctx leaked in {tool.name}"


# --- Daemon tools ---


@pytest.mark.asyncio
async def test_ping(mcp_client, mock_daemon):
    result = await mcp_client.call_tool("ping", {})
    assert result.data == "pong"
    mock_daemon.call.assert_any_call("ping")


@pytest.mark.asyncio
async def test_get_weather(mcp_client):
    result = await mcp_client.call_tool("get_weather", {})
    assert "32" in result.data and "Boston" in result.data


@pytest.mark.asyncio
async def test_get_time(mcp_client, mock_daemon):
    result = await mcp_client.call_tool("get_time", {})
    assert "2026" in result.data and "New_York" in result.data

    # With explicit timezone
    await mcp_client.call_tool("get_time", {"timezone": "US/Pacific"})
    mock_daemon.call.assert_any_call("refresh_time", timezone="US/Pacific")


@pytest.mark.asyncio
async def test_get_token_usage(mcp_client):
    result = await mcp_client.call_tool("get_token_usage", {})
    assert json.loads(result.data)["5h"]["used"] == 1000


# --- Spotify ---


@pytest.mark.asyncio
async def test_spotify_play_and_device_cache(mcp_client, mock_spotify_session):
    """Spotify executes commands, includes device list, and caches devices."""
    result = await mcp_client.call_tool("spotify", {"command": 'play "jazz"'})
    assert result.data["status"] == "ok"
    assert result.data["available_devices"] == ["Den", "Kitchen"]

    # Second call should use cached devices
    await mcp_client.call_tool("spotify", {"command": "pause"})
    device_calls = [c for c in mock_spotify_session.run.call_args_list if c.args[0] == "get devices"]
    assert len(device_calls) == 1


# --- Error handling ---


@pytest.mark.asyncio
async def test_daemon_not_running(mock_spotify_session):
    dead_daemon = MagicMock()
    dead_daemon.is_daemon_running.return_value = False

    import clarvis.spotify_tools as st

    st._device_cache.update({"names": None, "ts": 0})
    app = create_app(daemon_client=dead_daemon, get_session=lambda: mock_spotify_session)
    async with Client(app) as c:
        result = await c.call_tool("ping", {})
        assert "not running" in result.data


@pytest.mark.asyncio
async def test_spotify_session_error(mock_daemon):
    broken = MagicMock()
    broken.run.side_effect = Exception("Connection failed")

    import clarvis.spotify_tools as st

    st._device_cache.update({"names": None, "ts": 0})
    app = create_app(daemon_client=mock_daemon, get_session=lambda: broken)
    async with Client(app) as c:
        result = await c.call_tool("spotify", {"command": "now playing"})
        assert "Connection failed" in result.data["error"]
