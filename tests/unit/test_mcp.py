"""MCP tool surface — port isolation, visibility scoping, error handling, functional flows.

Covers standard vs home tool separation, knowledge tools, spotify error path,
visibility/permission scoping, signal emission, and timer flows.
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
    daemon.state.get.side_effect = lambda key, default=None: {
        "weather": {"temperature": 32, "description": "clear", "wind_speed": 10, "city": "Boston"},
    }.get(key, default)
    daemon.refresh.refresh_weather.return_value = {"temperature": 32, "description": "clear"}
    daemon.refresh.refresh_time.return_value = {"timestamp": "2026-02-06T12:00:00", "timezone": "America/New_York"}

    daemon.memory_store = None
    daemon.hindsight_backend = MagicMock()
    daemon.hindsight_backend.ready = True
    daemon.hindsight_backend.visible_banks.return_value = ["parletre", "agora"]
    daemon.hindsight_backend.default_bank.return_value = "parletre"
    daemon.hindsight_backend.store_facts = AsyncMock(return_value=["fact-001"])
    daemon.hindsight_backend.recall = AsyncMock(
        return_value={"results": [{"id": "fact-001", "content": "test fact", "fact_type": "world"}], "entities": []}
    )
    daemon.hindsight_backend.update_fact = AsyncMock(
        return_value={"success": True, "old_id": "fact-001", "new_ids": ["fact-002"]}
    )
    daemon.hindsight_backend.delete_fact = AsyncMock(return_value={"status": "ok"})
    daemon.hindsight_backend.list_facts = AsyncMock(
        return_value={"items": [{"id": "fact-001", "content": "a memory", "fact_type": "world"}], "total": 1}
    )
    daemon.hindsight_backend.list_mental_models = AsyncMock(return_value=[])
    daemon.hindsight_backend.list_observations = AsyncMock(return_value=[])
    daemon.hindsight_backend.get_bank_stats = AsyncMock(return_value={"total_facts": 1})

    daemon.cognee_backend = MagicMock()
    daemon.cognee_backend.ready = True
    daemon.cognee_backend.search = AsyncMock(return_value=[{"result": "knowledge result", "dataset_name": "knowledge"}])
    daemon.cognee_backend.ingest = AsyncMock(return_value={"status": "ok", "dataset": "knowledge", "tags": []})
    daemon.cognee_backend.list_entities = AsyncMock(
        return_value=[{"id": "ent-001", "name": "Test Entity", "type": "Person"}]
    )
    daemon.cognee_backend.list_facts = AsyncMock(
        return_value=[{"source_id": "ent-001", "target_id": "ent-002", "relationship": "knows", "properties": {}}]
    )
    daemon.cognee_backend.update_entity = AsyncMock(
        return_value={"status": "ok", "entity_id": "ent-001", "updated_fields": ["name"]}
    )
    daemon.cognee_backend.merge_entities = AsyncMock(
        return_value={"status": "ok", "survivor_id": "ent-001", "merged_count": 1}
    )
    daemon.cognee_backend.delete = AsyncMock(return_value={"status": "ok", "deleted_id": "ent-003"})
    daemon.cognee_backend.build_communities = AsyncMock(return_value={"status": "ok"})

    daemon.staging_store = MagicMock()
    daemon.staging_store.list_staged.return_value = []
    daemon.memory_service = None
    daemon.context_accumulator = MagicMock()
    daemon.context_accumulator.get_pending.return_value = {
        "sessions_since_last": [],
        "staged_items": [],
        "last_check_in": "2026-02-06T12:00:00+00:00",
    }

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
    app = create_app(daemon=mock_daemon, tool_config=STANDARD_TOOLS, get_session=lambda: mock_spotify)
    async with Client(app) as c:
        yield c


@pytest_asyncio.fixture
async def memory_client(mock_daemon, mock_spotify):
    app = create_app(daemon=mock_daemon, tool_config=HOME_TOOLS, get_session=lambda: mock_spotify)
    async with Client(app) as c:
        yield c


# ── Tool surface per port ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_standard_tools_registered(client):
    """Standard port has core tools but NOT memory, spotify, timers, or prompt_response."""
    tools = await client.list_tools()
    names = {t.name for t in tools}
    assert {"ping", "get_context"} <= names
    assert "clautify" not in names
    assert "set_timer" not in names
    assert "prompt_response" not in names
    assert "remember" not in names
    assert "knowledge" not in names


@pytest.mark.asyncio
async def test_knowledge_tools_registered(memory_client):
    """Home port has all knowledge tools."""
    tools = await memory_client.list_tools()
    names = {t.name for t in tools}
    assert {
        "knowledge",
        "ingest",
        "entities",
        "relations",
        "update_entity",
        "merge_entities",
        "delete_entity",
        "build_communities",
    } <= names


# ── Error handling ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_spotify_error(mock_daemon):
    """Spotify exceptions are surfaced as error text, not crashes."""
    broken = MagicMock()
    broken.run.side_effect = Exception("Connection failed")
    app = create_app(daemon=mock_daemon, tool_config=HOME_TOOLS, get_session=lambda: broken)
    async with Client(app) as c:
        r = await c.call_tool("clautify", {"command": "now playing"})
        assert "Connection failed" in r.data


# ── Visibility & permissions ────────────────────────────────────────


@pytest.mark.asyncio
async def test_recall_restricted_bank(mock_daemon, mock_spotify):
    """Masked agent (visibility=all) cannot search parletre."""
    tool_config = {
        "memory": {"visibility": "all"},
        "spotify": True,
        "timers": True,
        "channels": True,
        "prompt_response": True,
    }
    mock_daemon.hindsight_backend.visible_banks.return_value = ["agora"]
    mock_daemon.hindsight_backend.default_bank.return_value = "agora"
    app = create_app(daemon=mock_daemon, tool_config=tool_config, get_session=lambda: mock_spotify)
    async with Client(app) as c:
        r = await c.call_tool("recall", {"query": "test", "bank": "parletre"})
        assert "Error" in r.content[0].text
        assert "not accessible" in r.content[0].text


@pytest.mark.asyncio
async def test_channel_agent_no_write_tools(mock_daemon, mock_spotify):
    """Channel agents (visibility=all) only get search tools, no write/ingest/delete."""
    tool_config = {
        "memory": {"visibility": "all"},
        "spotify": False,
        "timers": False,
        "channels": True,
        "prompt_response": False,
    }
    mock_daemon.hindsight_backend.visible_banks.return_value = ["agora"]
    mock_daemon.hindsight_backend.default_bank.return_value = "agora"
    app = create_app(daemon=mock_daemon, tool_config=tool_config, get_session=lambda: mock_spotify)
    async with Client(app) as c:
        tools = await c.list_tools()
        names = {t.name for t in tools}
        assert "recall" in names
        assert "knowledge" in names
        # Write/home-only tools must NOT be present
        assert "remember" not in names
        assert "update_fact" not in names
        assert "forget" not in names
        assert "ingest" not in names
        assert "update_entity" not in names
        assert "merge_entities" not in names
        assert "delete_entity" not in names


# ── Signal emission ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prompt_response_signal(memory_client, mock_daemon):
    """prompt_response on home client emits voice:prompt_reply signal."""
    received = []
    mock_daemon.bus.on("voice:prompt_reply", lambda sig, **kw: received.append(True))
    r = await memory_client.call_tool("prompt_response", {})
    assert "Listening" in r.data
    # Signal delivers via call_soon_threadsafe on background loop — yield
    await asyncio.sleep(0.1)
    assert received, "voice:prompt_reply signal was not emitted"


# ── Timer functional flows ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_timer(memory_client):
    """Set then cancel — verifies cross-call state."""
    await memory_client.call_tool("set_timer", {"name": "x", "duration": "60"})
    r = await memory_client.call_tool("cancel_timer", {"name": "x"})
    assert "Cancelled" in r.data


@pytest.mark.asyncio
async def test_list_timers(memory_client):
    """Set then list — verifies timer appears."""
    r = await memory_client.call_tool("list_timers", {})
    assert "No active timers" in r.data
    await memory_client.call_tool("set_timer", {"name": "a", "duration": "5m"})
    r = await memory_client.call_tool("list_timers", {})
    assert "a" in r.data
