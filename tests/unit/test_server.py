"""In-memory MCP server tests using FastMCP 2.x Client.

Tests the full tool surface through the MCP protocol without subprocess or network.
Dependencies (daemon client, Clautify player) are mocked via create_app() factory.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from fastmcp import Client

from clarvis.server import create_app
from clarvis.widget.config import WidgetConfig, ThemeConfig, DisplayConfig, TestingConfig, MusicConfig


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
def mock_player():
    """Mock Clautify player."""
    player = MagicMock()
    player.now_playing.return_value = {
        "title": "Test Song", "artist": "Test Artist",
        "album": "Test Album", "state": "PLAYING",
    }
    player.play.return_value = {"status": "ok"}
    player.pause.return_value = {"status": "ok"}
    player.skip.return_value = {"status": "ok"}
    player.previous.return_value = {"status": "ok"}
    player.volume.return_value = {"level": 50}
    player.mute.return_value = {"muted": False}
    player.shuffle.return_value = {"enabled": False}
    player.repeat.return_value = {"mode": "off"}
    player.clear_queue.return_value = {"status": "ok"}
    player.get_queue.return_value = [{"title": "Song 1", "artist": "Artist 1"}]
    player.search.return_value = [{"title": "Found Song", "artist": "Found Artist"}]
    player.search_and_play.return_value = {
        "status": "ok",
        "search_results": [{"title": "Jazz Track"}],
        "played_index": 0,
    }
    player.queue.return_value = {"status": "ok", "queued": 1}
    player.play_album.return_value = {"status": "ok", "tracks": 10}
    player.spotify_playlists.return_value = [{"id": "sp:1", "title": "My Playlist"}]
    player.spotify_playlist_tracks.return_value = [{"title": "Track 1"}]
    player.sonos_playlists.return_value = [{"id": "s:1", "title": "Sonos Playlist"}]
    return player


@pytest.fixture
def clautify_config():
    """Config with clautify backend for music tools."""
    return WidgetConfig(
        theme=ThemeConfig(), display=DisplayConfig(), testing=TestingConfig(),
        music=MusicConfig(backend="clautify"),
    )


@pytest_asyncio.fixture
async def mcp_client(mock_daemon, mock_player, clautify_config):
    """In-memory MCP client connected to a test app with mocked deps."""
    with patch("clarvis.widget.config.get_config", return_value=clautify_config):
        app = create_app(daemon_client=mock_daemon, get_player=lambda: mock_player)
    async with Client(app) as c:
        yield c


# --- Tool Discovery ---

@pytest.mark.asyncio
async def test_all_tools_registered(mcp_client):
    """All 26 tools should be accessible through the MCP protocol."""
    tools = await mcp_client.list_tools()
    names = {t.name for t in tools}
    assert len(names) == 26

    # Daemon tools
    assert {"ping", "get_weather", "get_time", "get_token_usage", "get_music_context"} <= names
    # Session tools
    assert {"list_active_sessions", "get_session_thoughts", "get_latest_thought"} <= names
    # Music tools (mounted sub-server)
    assert {"search_and_play", "search", "now_playing", "play", "pause", "volume"} <= names


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


# --- Music Tools (mounted sub-server) ---

@pytest.mark.asyncio
async def test_now_playing(mcp_client, mock_player):
    result = await mcp_client.call_tool("now_playing", {})
    assert result.data["title"] == "Test Song"
    mock_player.now_playing.assert_called_once()


@pytest.mark.asyncio
async def test_play(mcp_client, mock_player):
    result = await mcp_client.call_tool("play", {})
    assert result.data["status"] == "ok"
    mock_player.play.assert_called_once()


@pytest.mark.asyncio
async def test_pause(mcp_client, mock_player):
    result = await mcp_client.call_tool("pause", {})
    assert result.data["status"] == "ok"
    mock_player.pause.assert_called_once()


@pytest.mark.asyncio
async def test_volume_get(mcp_client, mock_player):
    result = await mcp_client.call_tool("volume", {})
    assert result.data["level"] == 50
    mock_player.volume.assert_called_once_with(None)


@pytest.mark.asyncio
async def test_volume_set_absolute(mcp_client, mock_player):
    await mcp_client.call_tool("volume", {"level": "75"})
    mock_player.volume.assert_called_with(75)


@pytest.mark.asyncio
async def test_volume_set_relative(mcp_client, mock_player):
    await mcp_client.call_tool("volume", {"level": "+10"})
    mock_player.volume.assert_called_with("+10")


@pytest.mark.asyncio
async def test_search_and_play(mcp_client, mock_player):
    result = await mcp_client.call_tool("search_and_play", {"query": "jazz"})
    assert result.data["status"] == "ok"
    mock_player.search_and_play.assert_called_once_with(
        "jazz", category="tracks", index=0, start_at=None, clear=True,
    )


@pytest.mark.asyncio
async def test_search(mcp_client, mock_player):
    result = await mcp_client.call_tool("search", {"query": "rock"})
    data = json.loads(result.content[0].text)
    assert len(data) == 1
    assert data[0]["title"] == "Found Song"


@pytest.mark.asyncio
async def test_skip(mcp_client, mock_player):
    await mcp_client.call_tool("skip", {"count": 2})
    mock_player.skip.assert_called_once_with(2)


# --- Error Handling ---

@pytest.mark.asyncio
async def test_ping_daemon_not_running(mock_player, clautify_config):
    """When daemon isn't running, tools should return error messages, not crash."""
    dead_daemon = MagicMock()
    dead_daemon.is_daemon_running.return_value = False

    with patch("clarvis.widget.config.get_config", return_value=clautify_config):
        app = create_app(daemon_client=dead_daemon, get_player=lambda: mock_player)
    async with Client(app) as c:
        result = await c.call_tool("ping", {})
        assert "not running" in result.data


@pytest.mark.asyncio
async def test_music_tool_player_error(mock_daemon, clautify_config):
    """When player throws, music tools return error dict."""
    broken_player = MagicMock()
    broken_player.now_playing.side_effect = Exception("Sonos unreachable")

    with patch("clarvis.widget.config.get_config", return_value=clautify_config):
        app = create_app(daemon_client=mock_daemon, get_player=lambda: broken_player)
    async with Client(app) as c:
        result = await c.call_tool("now_playing", {})
        assert "error" in result.data
        assert "Sonos unreachable" in result.data["error"]


# --- Spotify Backend ---

@pytest.fixture
def spotapi_config():
    return WidgetConfig(
        theme=ThemeConfig(), display=DisplayConfig(), testing=TestingConfig(),
        music=MusicConfig(backend="spotapi"),
    )


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


@pytest.mark.asyncio
async def test_spotapi_backend_mounts_spotify_tool(mock_daemon, spotapi_config, mock_spotify_session):
    """When music backend is spotapi, the spotify tool is available and returns device list."""
    import clarvis.spotify_tools as st
    st._device_cache.update({"names": None, "ts": 0})  # reset cache between tests

    with patch("clarvis.widget.config.get_config", return_value=spotapi_config):
        app = create_app(
            daemon_client=mock_daemon,
            get_session=lambda: mock_spotify_session,
        )
    async with Client(app) as c:
        result = await c.call_tool("spotify", {"command": 'play "jazz"'})
        assert result.data["status"] == "ok"
        assert result.data["available_devices"] == ["Den", "Kitchen"]


@pytest.mark.asyncio
async def test_spotapi_devices_cached_across_calls(mock_daemon, spotapi_config, mock_spotify_session):
    """Device list is fetched once and cached for subsequent calls."""
    import clarvis.spotify_tools as st
    st._device_cache.update({"names": None, "ts": 0})

    with patch("clarvis.widget.config.get_config", return_value=spotapi_config):
        app = create_app(
            daemon_client=mock_daemon,
            get_session=lambda: mock_spotify_session,
        )
    async with Client(app) as c:
        await c.call_tool("spotify", {"command": "now playing"})
        await c.call_tool("spotify", {"command": "pause"})

        # "get devices" called once (first invocation), then cached
        device_calls = [c for c in mock_spotify_session.run.call_args_list if c.args[0] == "get devices"]
        assert len(device_calls) == 1


@pytest.mark.asyncio
async def test_spotapi_backend_no_clautify_tools(mock_daemon, spotapi_config):
    """Spotapi backend should not expose clautify tools like now_playing."""
    with patch("clarvis.widget.config.get_config", return_value=spotapi_config):
        app = create_app(daemon_client=mock_daemon, get_session=lambda: MagicMock())
    async with Client(app) as c:
        tool_names = {t.name for t in await c.list_tools()}
        assert "spotify" in tool_names
        assert "now_playing" not in tool_names
        assert "play" not in tool_names
