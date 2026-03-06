"""Memory MCP tools — visibility scoping, permission gates, validation, error paths.

Only tests behaviors that matter: access control, field mapping, validation,
and graceful degradation. Trivial mock-returns-mock CRUD tests removed.
"""

import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

pytest.importorskip("asyncpg", reason="asyncpg not installed (memory extra required)")

from fastmcp import Client

from clarvis.mcp.server import CLARVIS_TOOLS, create_app

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


def _make_mock_store():
    store = MagicMock()
    store.ready = True
    store.visible_banks.return_value = ["parletre", "agora"]
    store.default_bank.return_value = "parletre"
    store.store_facts = AsyncMock(return_value=["fact-001"])
    store.recall = AsyncMock(
        return_value={
            "results": [
                {"id": "fact-001", "content": "test fact", "fact_type": "world"},
            ],
            "entities": [{"name": "TestEntity"}],
        }
    )
    store.delete_fact = AsyncMock(return_value={"status": "ok"})
    store.update_fact = AsyncMock(return_value={"success": True, "old_id": "fact-001", "new_ids": ["fact-002"]})
    store.list_facts = AsyncMock(
        return_value={
            "items": [{"id": "fact-001", "content": "a memory", "fact_type": "world"}],
            "total": 1,
        }
    )
    store.list_mental_models = AsyncMock(return_value=[])
    store.list_observations = AsyncMock(return_value=[])
    store.get_observation = AsyncMock(return_value=None)
    store.get_bank_stats = AsyncMock(return_value={"total_facts": 42, "pending_consolidation": 5})
    store.list_directives = AsyncMock(return_value=[])
    store.create_directive = AsyncMock(return_value={"id": "dir-001"})
    store.update_directive = AsyncMock(return_value={})
    store.delete_directive = AsyncMock(return_value={})
    store.get_bank_profile = AsyncMock(
        return_value={"name": "parletre", "mission": "personal memory", "disposition": {"skepticism": 3}}
    )
    store.set_bank_mission = AsyncMock(return_value=None)
    store.update_bank_disposition = AsyncMock(return_value=None)
    return store


@pytest.fixture
def mock_daemon(loop):
    daemon = MagicMock()
    daemon.state.get.side_effect = lambda key, default=None: {
        "weather": {"temperature": 32, "description": "clear", "wind_speed": 10, "city": "Boston"},
    }.get(key, default)
    daemon.refresh.refresh_weather.return_value = {"temperature": 32, "description": "clear"}
    daemon.refresh.refresh_time.return_value = {"timestamp": "2026-02-06T12:00:00", "timezone": "America/New_York"}
    daemon.memory_store = _make_mock_store()
    daemon.hindsight_backend = daemon.memory_store
    daemon.cognee_backend = None
    daemon.staging_store = None
    daemon.bus = MagicMock()
    daemon.channel_manager = None
    daemon.context_accumulator = MagicMock()
    daemon.context_accumulator.get_pending.return_value = {
        "sessions_since_last": [],
        "staged_items": [],
        "last_check_in": "2026-02-06T12:00:00+00:00",
    }
    return daemon


@pytest_asyncio.fixture
async def memory_client(mock_daemon):
    app = create_app(daemon=mock_daemon, tool_config=CLARVIS_TOOLS)
    async with Client(app) as c:
        yield c


# ── Tool surface ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_memory_tools_registered(memory_client):
    """All memory tools should be registered on the home port."""
    tools = await memory_client.list_tools()
    names = {t.name for t in tools}
    expected = {
        "recall",
        "remember",
        "update_fact",
        "forget",
        "list_facts",
        "list_models",
        "search_models",
        "create_model",
        "update_model",
        "delete_model",
        "list_observations",
        "get_observation",
        "audit",
        "stats",
        "list_directives",
        "create_directive",
        "update_directive",
        "delete_directive",
        "get_profile",
        "set_mission",
        "set_disposition",
    }
    assert expected <= names, f"Missing tools: {expected - names}"


@pytest.mark.asyncio
async def test_no_ctx_leakage(memory_client):
    """ctx parameter must not appear in tool schemas."""
    tools = await memory_client.list_tools()
    # Check all Hindsight memory tools (no common prefix now, check individually)
    memory_tools = {
        "recall",
        "remember",
        "update_fact",
        "forget",
        "list_facts",
        "list_models",
        "search_models",
        "create_model",
        "update_model",
        "delete_model",
        "list_observations",
        "get_observation",
        "audit",
        "stats",
        "unconsolidated",
        "related_observations",
        "consolidate",
        "stale_models",
        "list_directives",
        "create_directive",
        "update_directive",
        "delete_directive",
        "get_profile",
        "set_mission",
        "set_disposition",
    }
    for t in tools:
        if t.name in memory_tools:
            assert "ctx" not in t.inputSchema.get("properties", {}), f"ctx leaked in {t.name}"


# ── Visibility & permissions ────────────────────────────────────────


@pytest.mark.asyncio
async def test_recall_restricted_bank(mock_daemon):
    """Factoria (visibility=all) cannot search parletre."""
    tool_config = {
        "memory": {"visibility": "all"},
        "spotify": False,
        "timers": False,
        "channels": True,
        "prompt_response": False,
    }
    mock_daemon.memory_store.visible_banks.return_value = ["agora"]
    mock_daemon.memory_store.default_bank.return_value = "agora"
    app = create_app(daemon=mock_daemon, tool_config=tool_config)
    async with Client(app) as c:
        r = await c.call_tool("recall", {"query": "test", "bank": "parletre"})
        assert "Error" in r.content[0].text
        assert "not accessible" in r.content[0].text


@pytest.mark.asyncio
async def test_channel_agent_only_gets_recall(mock_daemon):
    """Factoria (visibility=all) only gets recall, no write tools."""
    tool_config = {
        "memory": {"visibility": "all"},
        "spotify": False,
        "timers": False,
        "channels": False,
        "prompt_response": False,
    }
    mock_daemon.memory_store.visible_banks.return_value = ["agora"]
    mock_daemon.memory_store.default_bank.return_value = "agora"
    app = create_app(daemon=mock_daemon, tool_config=tool_config)
    async with Client(app) as c:
        tools = await c.list_tools()
        names = {t.name for t in tools}
        assert "recall" in names
        clarvis_only = {
            "remember",
            "update_fact",
            "forget",
            "list_facts",
            "list_models",
            "search_models",
            "create_model",
            "update_model",
            "delete_model",
            "list_observations",
            "get_observation",
            "audit",
            "stats",
            "list_directives",
            "create_directive",
            "update_directive",
            "delete_directive",
            "get_profile",
            "set_mission",
            "set_disposition",
        }
        for tool_name in clarvis_only:
            assert tool_name not in names, f"{tool_name} should not be available to Factoria"


# ── Field mapping & validation ──────────────────────────────────────


@pytest.mark.asyncio
async def test_remember_with_type_and_entities(memory_client, mock_daemon):
    """FactInput construction preserves all fields."""
    r = await memory_client.call_tool(
        "remember",
        {
            "content": "likes coffee",
            "fact_type": "opinion",
            "confidence": 0.9,
            "entities": ["Shepard"],
            "tags": ["preferences"],
        },
    )
    assert "Stored" in r.content[0].text
    fact_input = mock_daemon.memory_store.store_facts.call_args[0][0][0]
    assert fact_input.fact_text == "likes coffee"
    assert fact_input.fact_type == "opinion"
    assert fact_input.confidence == 0.9
    assert fact_input.entities == ["Shepard"]
    assert fact_input.tags == ["preferences"]


@pytest.mark.asyncio
async def test_update_fact_requires_content(memory_client):
    """update without content returns validation error."""
    r = await memory_client.call_tool("update_fact", {"fact_id": "fact-001"})
    assert "Error" in r.content[0].text
    assert "content is required" in r.content[0].text


@pytest.mark.asyncio
async def test_update_fact_failure(memory_client, mock_daemon):
    """Backend failure is surfaced to agent."""
    mock_daemon.memory_store.update_fact = AsyncMock(return_value={"success": False, "message": "fact not found"})
    r = await memory_client.call_tool("update_fact", {"fact_id": "bad-id", "content": "text"})
    assert "failed" in r.content[0].text.lower()


@pytest.mark.asyncio
async def test_audit_uses_last_checkin(memory_client, mock_daemon):
    """Audit reads last_check_in from ContextAccumulator, not from a since param."""
    r = await memory_client.call_tool("audit", {})
    # Should succeed without a since param — reads from ContextAccumulator
    assert "Facts since" in r.content[0].text


# ── Graceful degradation ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recall_store_not_ready(mock_daemon):
    """Returns error when store is not ready."""
    mock_daemon.memory_store.ready = False
    app = create_app(daemon=mock_daemon, tool_config=CLARVIS_TOOLS)
    async with Client(app) as c:
        r = await c.call_tool("recall", {"query": "test"})
        assert "Error" in r.content[0].text
        assert "not available" in r.content[0].text


@pytest.mark.asyncio
async def test_remember_store_not_ready(mock_daemon):
    """Returns error when store is not ready."""
    mock_daemon.memory_store.ready = False
    app = create_app(daemon=mock_daemon, tool_config=CLARVIS_TOOLS)
    async with Client(app) as c:
        r = await c.call_tool("remember", {"content": "test"})
        assert "Error" in r.content[0].text
        assert "not available" in r.content[0].text
