"""Tests for the full MCP tool surface.

Every tool is tested through Client(app).call_tool() — the same interface
agents use. One file covers standard tools, spotify, memory, knowledge,
and timers.
"""

import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastmcp import Client

from clarvis.channels.memory_context import build_memory_grounding
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

    # Hindsight backend (replaces old DualMemoryService)
    daemon.hindsight_backend = MagicMock()
    daemon.hindsight_backend.ready = True
    daemon.hindsight_backend.visible_banks.return_value = ["parletre", "agora"]
    daemon.hindsight_backend.retain = AsyncMock(return_value=[{"id": "fact-001", "fact_type": "world"}])
    daemon.hindsight_backend.recall = AsyncMock(
        return_value={
            "results": [{"id": "fact-001", "content": "test fact", "fact_type": "world"}],
            "entities": [],
        }
    )
    daemon.hindsight_backend.update = AsyncMock(
        return_value={"success": True, "old_id": "fact-001", "new_ids": ["fact-002"]}
    )
    daemon.hindsight_backend.forget = AsyncMock(return_value={"status": "ok"})
    daemon.hindsight_backend.list_memories = AsyncMock(
        return_value={"items": [{"id": "fact-001", "content": "a memory", "fact_type": "world"}], "total": 1}
    )

    # Cognee backend
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

    # Staging store
    daemon.staging_store = MagicMock()
    daemon.staging_store.list_staged.return_value = []

    # Legacy compat
    daemon.memory_service = None

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
    """Home client (memory + knowledge + prompt_response)."""
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
    assert "knowledge_search" not in names


@pytest.mark.asyncio
async def test_memory_tools_registered(memory_client):
    tools = await memory_client.list_tools()
    names = {t.name for t in tools}
    assert {"memory_add", "memory_search", "memory_forget", "memory_update", "memory_list", "memory_staged"} <= names
    # No ctx leakage
    for t in tools:
        assert "ctx" not in t.inputSchema.get("properties", {}), f"ctx leaked in {t.name}"


@pytest.mark.asyncio
async def test_knowledge_tools_registered(memory_client):
    tools = await memory_client.list_tools()
    names = {t.name for t in tools}
    assert {
        "knowledge_search",
        "knowledge_ingest",
        "knowledge_entities",
        "knowledge_facts",
        "knowledge_update",
        "knowledge_merge",
        "knowledge_delete",
        "knowledge_communities",
    } <= names


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


# ── Memory tools (Hindsight) ───────────────────────────────────────


@pytest.mark.asyncio
async def test_memory_add(memory_client, mock_daemon):
    r = await memory_client.call_tool("memory_add", {"content": "test fact"})
    text = r.content[0].text
    assert "Retained" in text
    mock_daemon.hindsight_backend.retain.assert_awaited_once()


@pytest.mark.asyncio
async def test_memory_add_with_type(memory_client, mock_daemon):
    r = await memory_client.call_tool("memory_add", {"content": "a belief", "fact_type": "opinion", "confidence": 0.8})
    text = r.content[0].text
    assert "Retained" in text
    call_kwargs = mock_daemon.hindsight_backend.retain.call_args[1]
    assert call_kwargs.get("fact_type") == "opinion"
    assert call_kwargs.get("confidence") == 0.8


@pytest.mark.asyncio
async def test_memory_search(memory_client):
    r = await memory_client.call_tool("memory_search", {"query": "test"})
    assert "test fact" in r.content[0].text


@pytest.mark.asyncio
async def test_memory_search_restricted_bank(mock_daemon, mock_spotify):
    """Masked agent (visibility=all) cannot search parletre."""
    tool_config = {
        "memory": {"visibility": "all"},
        "spotify": True,
        "timers": True,
        "channels": True,
        "prompt_response": True,
    }
    mock_daemon.hindsight_backend.visible_banks.return_value = ["agora"]
    app = create_app(daemon=mock_daemon, tool_config=tool_config, get_session=lambda: mock_spotify)
    async with Client(app) as c:
        r = await c.call_tool("memory_search", {"query": "test", "bank": "parletre"})
        assert "Error" in r.content[0].text
        assert "not accessible" in r.content[0].text


@pytest.mark.asyncio
async def test_memory_update(memory_client, mock_daemon):
    r = await memory_client.call_tool("memory_update", {"fact_id": "fact-001", "content": "updated text"})
    text = r.content[0].text
    assert "Updated" in text
    mock_daemon.hindsight_backend.update.assert_awaited_once()


@pytest.mark.asyncio
async def test_memory_forget(memory_client, mock_daemon):
    r = await memory_client.call_tool("memory_forget", {"fact_id": "fact-001"})
    text = r.content[0].text
    assert "Forgotten" in text
    mock_daemon.hindsight_backend.forget.assert_awaited_once()


@pytest.mark.asyncio
async def test_memory_list(memory_client):
    r = await memory_client.call_tool("memory_list", {})
    text = r.content[0].text
    assert "a memory" in text


@pytest.mark.asyncio
async def test_memory_staged_empty(memory_client):
    r = await memory_client.call_tool("memory_staged", {})
    assert "No staged changes" in r.content[0].text


# ── Knowledge tools (Cognee) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_knowledge_search(memory_client):
    r = await memory_client.call_tool("knowledge_search", {"query": "test"})
    assert "knowledge result" in r.content[0].text


@pytest.mark.asyncio
async def test_knowledge_ingest(memory_client, mock_daemon):
    r = await memory_client.call_tool("knowledge_ingest", {"content_or_path": "some text"})
    text = r.content[0].text
    assert "Ingested" in text
    mock_daemon.cognee_backend.ingest.assert_awaited_once()


@pytest.mark.asyncio
async def test_knowledge_entities(memory_client):
    r = await memory_client.call_tool("knowledge_entities", {})
    text = r.content[0].text
    assert "Test Entity" in text


@pytest.mark.asyncio
async def test_knowledge_facts(memory_client):
    r = await memory_client.call_tool("knowledge_facts", {})
    text = r.content[0].text
    assert "knows" in text


@pytest.mark.asyncio
async def test_knowledge_update(memory_client, mock_daemon):
    r = await memory_client.call_tool("knowledge_update", {"entity_id": "ent-001", "fields": '{"name": "Updated"}'})
    text = r.content[0].text
    assert "Updated" in text
    mock_daemon.cognee_backend.update_entity.assert_awaited_once()


@pytest.mark.asyncio
async def test_knowledge_merge(memory_client, mock_daemon):
    r = await memory_client.call_tool("knowledge_merge", {"entity_ids": "ent-001, ent-002"})
    text = r.content[0].text
    assert "Merged" in text
    mock_daemon.cognee_backend.merge_entities.assert_awaited_once()


@pytest.mark.asyncio
async def test_knowledge_delete(memory_client, mock_daemon):
    r = await memory_client.call_tool("knowledge_delete", {"node_id": "ent-003"})
    text = r.content[0].text
    assert "Deleted" in text
    mock_daemon.cognee_backend.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_knowledge_communities(memory_client, mock_daemon):
    r = await memory_client.call_tool("knowledge_communities", {})
    text = r.content[0].text
    assert "built" in text.lower()
    mock_daemon.cognee_backend.build_communities.assert_awaited_once()


# ── Visibility scoping ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_masked_agent_no_write_tools(mock_daemon, mock_spotify):
    """Masked agents (visibility=all) only get search tools, no write."""
    tool_config = {
        "memory": {"visibility": "all"},
        "spotify": False,
        "timers": False,
        "channels": True,
        "prompt_response": False,
    }
    mock_daemon.hindsight_backend.visible_banks.return_value = ["agora"]
    app = create_app(daemon=mock_daemon, tool_config=tool_config, get_session=lambda: mock_spotify)
    async with Client(app) as c:
        tools = await c.list_tools()
        names = {t.name for t in tools}
        assert "memory_search" in names
        assert "knowledge_search" in names
        # Write tools must NOT be present for masked agents
        assert "memory_add" not in names
        assert "memory_update" not in names
        assert "memory_forget" not in names
        assert "memory_list" not in names
        assert "memory_staged" not in names
        assert "knowledge_ingest" not in names
        assert "knowledge_update" not in names
        assert "knowledge_merge" not in names
        assert "knowledge_delete" not in names


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


# ── Memory grounding (moved from test_memory_context.py) ─────────


@pytest.mark.asyncio
async def test_build_memory_grounding_formats_context():
    """Should format Hindsight recall result into <memory_context> block."""
    backend = MagicMock()
    backend.ready = True
    backend.recall = AsyncMock(
        return_value={
            "results": [
                {"content": "likes coffee", "fact_type": "world"},
                {"content": "user is a developer", "fact_type": "world"},
            ],
            "entities": [{"name": "Shepard"}],
        }
    )

    transcript = [{"role": "user", "content": "tell me about myself"}]
    result = await build_memory_grounding(backend, "parletre", transcript)

    assert result.startswith("<memory_context>")
    assert result.endswith("</memory_context>")
    assert "likes coffee" in result
    assert "user is a developer" in result
    assert "Shepard" in result


@pytest.mark.asyncio
async def test_build_memory_grounding_empty_when_not_ready():
    """Should return empty string when backend is not ready."""
    backend = MagicMock()
    backend.ready = False

    result = await build_memory_grounding(backend, "parletre", [])
    assert result == ""


@pytest.mark.asyncio
async def test_build_memory_grounding_empty_when_none():
    """Should return empty string when hindsight_backend is None."""
    result = await build_memory_grounding(None, "parletre", [])
    assert result == ""


@pytest.mark.asyncio
async def test_build_memory_grounding_empty_when_no_results():
    """Should return empty string when recall returns no data."""
    backend = MagicMock()
    backend.ready = True
    backend.recall = AsyncMock(
        return_value={
            "results": [],
            "entities": [],
        }
    )

    result = await build_memory_grounding(backend, "parletre", [])
    assert result == ""


@pytest.mark.asyncio
async def test_build_memory_grounding_truncates_long_results():
    """Should truncate grounding body to ~2000 chars."""
    backend = MagicMock()
    backend.ready = True
    backend.recall = AsyncMock(
        return_value={
            "results": [{"content": "x" * 300, "fact_type": "world"} for _ in range(20)],
            "entities": [],
        }
    )

    result = await build_memory_grounding(backend, "parletre", [])
    body = result.replace("<memory_context>\n", "").replace("\n</memory_context>", "")
    assert len(body) <= 2003  # 2000 + "..."


@pytest.mark.asyncio
async def test_build_memory_grounding_handles_recall_error():
    """Should return empty string on recall error."""
    backend = MagicMock()
    backend.ready = True
    backend.recall = AsyncMock(return_value={"error": "boom"})

    result = await build_memory_grounding(backend, "parletre", [])
    assert result == ""


@pytest.mark.asyncio
async def test_build_memory_grounding_with_fact_types():
    """Should show fact type prefixes in grounding."""
    backend = MagicMock()
    backend.ready = True
    backend.recall = AsyncMock(
        return_value={
            "results": [
                {"content": "likes metal", "fact_type": "opinion", "confidence": 0.9},
                {"content": "works at MIT", "fact_type": "world"},
            ],
            "entities": [],
        }
    )

    result = await build_memory_grounding(backend, "parletre", [])
    assert "[opinion]" in result
    assert "[world]" in result
    assert "conf: 0.9" in result
