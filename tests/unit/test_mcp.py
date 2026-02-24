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

from clarvis.core.context import AppContext
from clarvis.core.signals import SignalBus
from clarvis.mcp.server import HOME_TOOLS, STANDARD_TOOLS, create_app
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

    # memory service (DualMemoryService interface)
    daemon.memory_service = MagicMock()
    daemon.memory_service._ready = True
    daemon.memory_service.add = AsyncMock(return_value={"status": "ok", "dataset": "parletre", "bytes": 10})
    daemon.memory_service.search = AsyncMock(return_value=[{"fact": "test fact"}])
    daemon.memory_service.forget = AsyncMock(return_value={"status": "ok", "deleted": "abc-123", "dataset": "parletre"})
    # memU backend for visibility checks
    daemon.memory_service._memu = MagicMock()
    daemon.memory_service._memu.visible_datasets.return_value = ["parletre", "agora"]

    # context accumulator
    daemon.context_accumulator = MagicMock()
    daemon.context_accumulator.get_pending.return_value = {
        "sessions_since_last": [],
        "staged_items": [],
        "last_check_in": "2026-02-06T12:00:00+00:00",
    }

    # timer service (real, not mocked — tests actual timer behavior)
    bus = SignalBus(loop)
    daemon.bus = bus
    ctx = AppContext(loop=loop, bus=bus, state=daemon.state, config=MagicMock())
    svc = TimerService(ctx=ctx, state_file=str(tmp_path / "timers.json"))
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
    """Standard client (no memory tools, no prompt_response)."""
    app = create_app(daemon=mock_daemon, tool_config=STANDARD_TOOLS, get_session=lambda: mock_spotify)
    async with Client(app) as c:
        yield c


@pytest_asyncio.fixture
async def memory_client(mock_daemon, mock_spotify):
    """Home client (memory + prompt_response)."""
    app = create_app(daemon=mock_daemon, tool_config=HOME_TOOLS, get_session=lambda: mock_spotify)
    async with Client(app) as c:
        yield c


# ── Tool surface ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_standard_tools_registered(client):
    tools = await client.list_tools()
    names = {t.name for t in tools}
    assert {"ping", "get_context"} <= names
    # spotify, timers, prompt_response, memory NOT on standard port
    assert "clautify" not in names
    assert "set_timer" not in names
    assert "prompt_response" not in names
    assert "memory_add" not in names


@pytest.mark.asyncio
async def test_memory_tools_registered(memory_client):
    tools = await memory_client.list_tools()
    names = {t.name for t in tools}
    assert {"memory_add", "memory_search", "memory_forget"} <= names
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
async def test_spotify_command(memory_client):
    r = await memory_client.call_tool("clautify", {"command": 'play "jazz"'})
    assert "jazz" in r.data


@pytest.mark.asyncio
async def test_spotify_error(mock_daemon):
    broken = MagicMock()
    broken.run.side_effect = Exception("Connection failed")
    app = create_app(daemon=mock_daemon, tool_config=HOME_TOOLS, get_session=lambda: broken)
    async with Client(app) as c:
        r = await c.call_tool("clautify", {"command": "now playing"})
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
async def test_memory_add_file(memory_client, mock_daemon, tmp_path):
    f = tmp_path / "notes.txt"
    f.write_text("hello world")
    r = await memory_client.call_tool("memory_add", {"file_path": str(f)})
    assert "Added" in r.content[0].text
    # File content should have been read and passed as text to .add()
    mock_daemon.memory_service.add.assert_awaited_once()
    call_args = mock_daemon.memory_service.add.call_args
    assert call_args[0][0] == "hello world"  # file contents passed as first arg


@pytest.mark.asyncio
async def test_memory_add_file_not_found(memory_client):
    r = await memory_client.call_tool("memory_add", {"file_path": "/nonexistent/file.txt"})
    assert "Error:" in r.content[0].text
    assert "not found" in r.content[0].text.lower()


@pytest.mark.asyncio
async def test_memory_add_both_data_and_file(memory_client, tmp_path):
    f = tmp_path / "notes.txt"
    f.write_text("hello")
    r = await memory_client.call_tool("memory_add", {"data": "text", "file_path": str(f)})
    assert "Error:" in r.content[0].text
    assert "exactly one" in r.content[0].text.lower()


@pytest.mark.asyncio
async def test_memory_add_neither_data_nor_file(memory_client):
    r = await memory_client.call_tool("memory_add", {})
    assert "Error:" in r.content[0].text


@pytest.mark.asyncio
async def test_memory_search(memory_client):
    r = await memory_client.call_tool("memory_search", {"query": "test"})
    assert "test fact" in r.content[0].text


@pytest.mark.asyncio
async def test_memory_forget(memory_client):
    r = await memory_client.call_tool("memory_forget", {"item_id": "abc-123", "dataset": "parletre"})
    assert "ok" in r.content[0].text


# ── prompt_response ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prompt_response_not_in_standard(client):
    """prompt_response should not be exposed on the standard port."""
    tools = await client.list_tools()
    names = {t.name for t in tools}
    assert "prompt_response" not in names


@pytest.mark.asyncio
async def test_prompt_response_signal(memory_client, mock_daemon):
    """prompt_response on home client should emit voice:prompt_reply signal."""
    received = []
    mock_daemon.bus.on("voice:prompt_reply", lambda sig, **kw: received.append(True))
    r = await memory_client.call_tool("prompt_response", {})
    assert "Listening" in r.data
    assert received, "voice:prompt_reply signal was not emitted"


# ── Timers ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_timer(memory_client):
    r = await memory_client.call_tool("set_timer", {"name": "egg", "duration": "5m", "label": "boiled"})
    assert "egg" in r.data


@pytest.mark.asyncio
async def test_set_timer_invalid(memory_client):
    r = await memory_client.call_tool("set_timer", {"name": "bad", "duration": "xyz"})
    assert "Error" in r.data


@pytest.mark.asyncio
async def test_cancel_timer(memory_client):
    await memory_client.call_tool("set_timer", {"name": "x", "duration": "60"})
    r = await memory_client.call_tool("cancel_timer", {"name": "x"})
    assert "Cancelled" in r.data


@pytest.mark.asyncio
async def test_list_timers(memory_client):
    r = await memory_client.call_tool("list_timers", {})
    assert "No active timers" in r.data
    await memory_client.call_tool("set_timer", {"name": "a", "duration": "5m"})
    r = await memory_client.call_tool("list_timers", {})
    assert "a" in r.data
