"""Memory MCP tools — visibility scoping, permission gates, validation, error paths.

Only tests behaviors that matter: access control, field mapping, validation,
and graceful degradation. Trivial mock-returns-mock CRUD tests removed.
"""

import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock

import pytest

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


def _make_mock_daemon(loop):
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


# ── Tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_memory_tool_surface_and_schema(loop):
    """All memory tools registered on Clarvis port, ctx not leaked in schemas."""
    daemon = _make_mock_daemon(loop)
    app = create_app(daemon=daemon, tool_config=CLARVIS_TOOLS)
    async with Client(app) as c:
        tools = await c.list_tools()
        names = {t.name for t in tools}

        # full tool surface check
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

        # ctx not exposed in any memory tool schema
        memory_tools = expected | {
            "unconsolidated",
            "related_observations",
            "consolidate",
            "stale_models",
        }
        for t in tools:
            if t.name in memory_tools:
                assert "ctx" not in t.inputSchema.get("properties", {}), f"ctx leaked in {t.name}"


@pytest.mark.asyncio
async def test_memory_permission_scoping(loop):
    """Bank restriction and tool restriction for channel agents."""
    daemon = _make_mock_daemon(loop)

    # Factoria (visibility=all) cannot search parletre
    tool_config = {
        "memory": {"visibility": "all"},
        "spotify": False,
        "timers": False,
        "channels": True,
        "prompt_response": False,
    }
    daemon.memory_store.visible_banks.return_value = ["agora"]
    daemon.memory_store.default_bank.return_value = "agora"
    app = create_app(daemon=daemon, tool_config=tool_config)
    async with Client(app) as c:
        r = await c.call_tool("recall", {"query": "test", "bank": "parletre"})
        assert "Error" in r.content[0].text
        assert "not accessible" in r.content[0].text

    # Factoria only gets recall, no write tools
    tool_config_no_channels = {
        "memory": {"visibility": "all"},
        "spotify": False,
        "timers": False,
        "channels": False,
        "prompt_response": False,
    }
    app2 = create_app(daemon=daemon, tool_config=tool_config_no_channels)
    async with Client(app2) as c:
        tools = await c.list_tools()
        names = {t.name for t in tools}
        assert "recall" in names

        # write/admin tools not available to Factoria
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


@pytest.mark.asyncio
async def test_remember_field_mapping_and_validation(loop):
    """Field mapping → validation error → backend failure handling."""
    daemon = _make_mock_daemon(loop)
    app = create_app(daemon=daemon, tool_config=CLARVIS_TOOLS)
    async with Client(app) as c:
        # correct field mapping preserves all fields
        r = await c.call_tool(
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
        fact_input = daemon.memory_store.store_facts.call_args[0][0][0]
        assert fact_input.fact_text == "likes coffee"
        assert fact_input.fact_type == "opinion"
        assert fact_input.confidence == 0.9
        assert fact_input.entities == ["Shepard"]
        assert fact_input.tags == ["preferences"]

        # update without content returns validation error
        r = await c.call_tool("update_fact", {"fact_id": "fact-001"})
        assert "Error" in r.content[0].text
        assert "content is required" in r.content[0].text

        # backend failure surfaced to agent
        daemon.memory_store.update_fact = AsyncMock(return_value={"success": False, "message": "fact not found"})
        r = await c.call_tool("update_fact", {"fact_id": "bad-id", "content": "text"})
        assert "failed" in r.content[0].text.lower()


@pytest.mark.asyncio
async def test_memory_graceful_degradation(loop):
    """Audit behavior and store-not-ready fallback."""
    daemon = _make_mock_daemon(loop)

    # audit reads last_check_in from ContextAccumulator
    app = create_app(daemon=daemon, tool_config=CLARVIS_TOOLS)
    async with Client(app) as c:
        r = await c.call_tool("audit", {})
        assert "Facts since" in r.content[0].text

    # store not ready returns error
    daemon.memory_store.ready = False
    app2 = create_app(daemon=daemon, tool_config=CLARVIS_TOOLS)
    async with Client(app2) as c:
        r = await c.call_tool("recall", {"query": "test"})
        assert "Error" in r.content[0].text
        assert "not available" in r.content[0].text
