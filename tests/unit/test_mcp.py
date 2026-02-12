"""Tests for the full MCP tool surface.

Every tool is tested through Client(app).call_tool() — the same interface
agents use. One file covers standard tools, spotify, memory, and timers.
"""

import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastmcp import Client

from clarvis.core.signals import SignalBus
from clarvis.server import create_app
from clarvis.services.timer_service import TimerService

# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def loop():
    _loop = asyncio.new_event_loop()
    t = threading.Thread(target=_loop.run_forever, daemon=True)
    t.start()
    yield _loop
    _loop.call_soon_threadsafe(_loop.stop)
    t.join(timeout=2)
    _loop.close()


@pytest.fixture
def mock_daemon(loop, tmp_path):
    daemon = MagicMock()

    # state
    daemon.state.get.side_effect = lambda key, default=None: {
        "weather": {"temperature": 32, "description": "clear", "wind_speed": 10, "city": "Boston"},
    }.get(key, default)

    # refresh
    daemon.refresh.refresh_weather.return_value = {"temperature": 32, "description": "clear"}
    daemon.refresh.refresh_time.return_value = {"timestamp": "2026-02-06T12:00:00", "timezone": "America/New_York"}

    # token usage
    daemon.token_usage_service = MagicMock()
    daemon.token_usage_service.get_usage.return_value = {"5h": {"used": 1000, "limit": 5000}}

    # memory service
    daemon.memory_service = MagicMock()
    daemon.memory_service._ready = True
    daemon.memory_service.add = AsyncMock(return_value={"status": "ok", "dataset": "shepard", "bytes": 10})
    daemon.memory_service.search = AsyncMock(return_value=[{"result": "test fact"}])
    daemon.memory_service.cognify = AsyncMock(return_value={"status": "ok", "dataset": "shepard"})
    daemon.memory_service.list_items = AsyncMock(
        return_value=[{"data_id": "abc-123", "preview": "Test fact", "created_at": "2026-02-06T12:00:00"}]
    )
    daemon.memory_service.delete = AsyncMock(return_value={"status": "ok", "deleted": "abc-123", "dataset": "shepard"})
    daemon.memory_service.status = AsyncMock(return_value={"ready": True})

    # context accumulator
    daemon.context_accumulator = MagicMock()
    daemon.context_accumulator.get_pending.return_value = {
        "sessions_since_last": [],
        "staged_items": [],
        "last_check_in": "2026-02-06T12:00:00+00:00",
    }

    # timer service (real, not mocked — tests actual timer behavior)
    bus = SignalBus(loop)
    svc = TimerService(bus=bus, loop=loop, state_file=str(tmp_path / "timers.json"))
    fut = asyncio.run_coroutine_threadsafe(_start_on_loop(svc), loop)
    fut.result(timeout=2)
    daemon.timer_service = svc

    yield daemon
    svc.stop()


async def _start_on_loop(svc):
    svc.start()


@pytest.fixture
def mock_spotify():
    session = MagicMock()
    session.run.return_value = {"status": "ok", "action": "play", "kind": "track", "target": "jazz"}
    return session


@pytest_asyncio.fixture
async def client(mock_daemon, mock_spotify):
    """Standard client (no memory tools)."""
    app = create_app(daemon=mock_daemon, get_session=lambda: mock_spotify)
    async with Client(app) as c:
        yield c


@pytest_asyncio.fixture
async def memory_client(mock_daemon, mock_spotify):
    """Memory-enabled client."""
    app = create_app(daemon=mock_daemon, get_session=lambda: mock_spotify, include_memory=True)
    async with Client(app) as c:
        yield c


# ── Tool surface ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_standard_tools_registered(client):
    tools = await client.list_tools()
    names = {t.name for t in tools}
    assert {"ping", "get_context", "spotify", "set_timer", "cancel_timer", "list_timers"} <= names
    # Memory tools NOT on standard port
    assert "memory_add" not in names


@pytest.mark.asyncio
async def test_memory_tools_registered(memory_client):
    tools = await memory_client.list_tools()
    names = {t.name for t in tools}
    assert {"memory_add", "memory_search", "memory_cognify", "memory_status", "check_in"} <= names
    # No ctx leakage
    for t in tools:
        assert "ctx" not in t.inputSchema.get("properties", {}), f"ctx leaked in {t.name}"


# ── Core tools ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ping(client):
    r = await client.call_tool("ping", {})
    assert r.data == "pong"


@pytest.mark.asyncio
async def test_get_context(client):
    r = await client.call_tool("get_context", {})
    assert "Boston" in r.data or "32" in r.data


# ── Spotify ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_spotify_command(client):
    r = await client.call_tool("spotify", {"command": 'play "jazz"'})
    assert "jazz" in r.data


@pytest.mark.asyncio
async def test_spotify_error(mock_daemon):
    broken = MagicMock()
    broken.run.side_effect = Exception("Connection failed")
    app = create_app(daemon=mock_daemon, get_session=lambda: broken)
    async with Client(app) as c:
        r = await c.call_tool("spotify", {"command": "now playing"})
        assert "Connection failed" in r.data


# ── Memory tools ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_memory_add(memory_client):
    r = await memory_client.call_tool("memory_add", {"data": "test fact"})
    assert "Added" in r.content[0].text


@pytest.mark.asyncio
async def test_memory_add_invalid_dataset(memory_client):
    r = await memory_client.call_tool("memory_add", {"data": "x", "dataset": "bogus"})
    assert "Error:" in r.content[0].text


@pytest.mark.asyncio
async def test_memory_search(memory_client):
    r = await memory_client.call_tool("memory_search", {"query": "test"})
    assert "test fact" in r.content[0].text


@pytest.mark.asyncio
async def test_check_in(memory_client):
    r = await memory_client.call_tool("check_in", {})
    text = r.data if hasattr(r, "data") else r.content[0].text
    assert "Last check-in:" in text


# ── Timers ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_timer(client):
    r = await client.call_tool("set_timer", {"name": "egg", "duration": "5m", "label": "boiled"})
    assert "egg" in r.data


@pytest.mark.asyncio
async def test_set_timer_invalid(client):
    r = await client.call_tool("set_timer", {"name": "bad", "duration": "xyz"})
    assert "Error" in r.data


@pytest.mark.asyncio
async def test_cancel_timer(client):
    await client.call_tool("set_timer", {"name": "x", "duration": "60"})
    r = await client.call_tool("cancel_timer", {"name": "x"})
    assert "Cancelled" in r.data


@pytest.mark.asyncio
async def test_list_timers(client):
    r = await client.call_tool("list_timers", {})
    assert "No active timers" in r.data
    await client.call_tool("set_timer", {"name": "a", "duration": "5m"})
    r = await client.call_tool("list_timers", {})
    assert "a" in r.data
