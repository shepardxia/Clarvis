"""Tests for CogneeMemoryService, memory MCP tools, ContextAccumulator, and command handlers."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastmcp import Client

from clarvis.memory_tools import create_memory_server
from clarvis.server import create_app
from clarvis.services.cognee_memory import CogneeMemoryService
from clarvis.services.context_accumulator import ContextAccumulator, extract_project_from_slug

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def memory_service():
    """A CogneeMemoryService that has been marked ready (bypassing start)."""
    svc = CogneeMemoryService()
    svc._ready = True
    return svc


@pytest.fixture
def unready_service():
    """A CogneeMemoryService that has NOT been started."""
    return CogneeMemoryService()


# ---------------------------------------------------------------------------
# CogneeMemoryService — not-ready guard
# ---------------------------------------------------------------------------


class TestNotReady:
    """All methods should return error dicts when service is not ready."""

    @pytest.mark.asyncio
    async def test_add_not_ready(self, unready_service):
        result = await unready_service.add("hello")
        assert result == {"error": "Memory service not available"}

    @pytest.mark.asyncio
    async def test_cognify_not_ready(self, unready_service):
        result = await unready_service.cognify()
        assert result == {"error": "Memory service not available"}

    @pytest.mark.asyncio
    async def test_search_not_ready(self, unready_service):
        result = await unready_service.search("test query")
        assert result == [{"error": "Memory service not available"}]

    @pytest.mark.asyncio
    async def test_status_not_ready(self, unready_service):
        result = await unready_service.status()
        assert result["ready"] is False


# ---------------------------------------------------------------------------
# CogneeMemoryService — happy-path with mocked cognee
# ---------------------------------------------------------------------------


class TestAdd:
    @pytest.mark.asyncio
    async def test_add_success(self, memory_service):
        mock_cognee = MagicMock()
        mock_cognee.add = AsyncMock()

        with patch.dict("sys.modules", {"cognee": mock_cognee}):
            result = await memory_service.add("some text", "test_ds")

        assert result["status"] == "ok"
        assert result["dataset"] == "test_ds"
        assert result["bytes"] == len("some text")
        mock_cognee.add.assert_awaited_once_with("some text", "test_ds")

    @pytest.mark.asyncio
    async def test_add_exception(self, memory_service):
        mock_cognee = MagicMock()
        mock_cognee.add = AsyncMock(side_effect=RuntimeError("boom"))

        with patch.dict("sys.modules", {"cognee": mock_cognee}):
            result = await memory_service.add("data")

        assert "error" in result
        assert "boom" in result["error"]


class TestCognify:
    @pytest.mark.asyncio
    async def test_cognify_success(self, memory_service):
        mock_cognee = MagicMock()
        mock_cognee.cognify = AsyncMock()

        with patch.dict("sys.modules", {"cognee": mock_cognee}):
            result = await memory_service.cognify("test_ds")

        assert result["status"] == "ok"
        assert result["dataset"] == "test_ds"
        mock_cognee.cognify.assert_awaited_once_with("test_ds")

    @pytest.mark.asyncio
    async def test_cognify_exception(self, memory_service):
        mock_cognee = MagicMock()
        mock_cognee.cognify = AsyncMock(side_effect=RuntimeError("graph error"))

        with patch.dict("sys.modules", {"cognee": mock_cognee}):
            result = await memory_service.cognify()

        assert "error" in result
        assert "graph error" in result["error"]


class TestSearch:
    @pytest.mark.asyncio
    async def test_search_success(self, memory_service):
        mock_search_type = MagicMock()
        mock_search_type.__getitem__ = MagicMock(return_value="GRAPH_COMPLETION")

        mock_cognee = MagicMock()
        mock_cognee.search = AsyncMock(return_value=[{"node": "A"}, {"node": "B"}])

        mock_search_mod = MagicMock()
        mock_search_mod.SearchType = mock_search_type

        with patch.dict(
            "sys.modules",
            {
                "cognee": mock_cognee,
                "cognee.api": MagicMock(),
                "cognee.api.v1": MagicMock(),
                "cognee.api.v1.search": mock_search_mod,
            },
        ):
            result = await memory_service.search("find nodes", top_k=5)

        assert len(result) == 2
        assert result[0] == {"node": "A"}

    @pytest.mark.asyncio
    async def test_search_exception(self, memory_service):
        mock_cognee = MagicMock()
        mock_search_mod = MagicMock()
        mock_search_mod.SearchType.__getitem__ = MagicMock(side_effect=KeyError("BAD_TYPE"))

        with patch.dict(
            "sys.modules",
            {
                "cognee": mock_cognee,
                "cognee.api": MagicMock(),
                "cognee.api.v1": MagicMock(),
                "cognee.api.v1.search": mock_search_mod,
            },
        ):
            result = await memory_service.search("query", search_type="BAD_TYPE")

        assert len(result) == 1
        assert "error" in result[0]

    @pytest.mark.asyncio
    async def test_search_normalizes_non_dict_results(self, memory_service):
        mock_search_type = MagicMock()
        mock_search_type.__getitem__ = MagicMock(return_value="GRAPH_COMPLETION")

        mock_cognee = MagicMock()
        mock_cognee.search = AsyncMock(return_value=["plain string", 42])

        mock_search_mod = MagicMock()
        mock_search_mod.SearchType = mock_search_type

        with patch.dict(
            "sys.modules",
            {
                "cognee": mock_cognee,
                "cognee.api": MagicMock(),
                "cognee.api.v1": MagicMock(),
                "cognee.api.v1.search": mock_search_mod,
            },
        ):
            result = await memory_service.search("query")

        assert result[0] == {"result": "plain string"}
        assert result[1] == {"result": "42"}


class TestStatus:
    @pytest.mark.asyncio
    async def test_status_ready(self, memory_service):
        mock_cognee = MagicMock()
        mock_cognee.__version__ = "0.5.1"

        with patch.dict("sys.modules", {"cognee": mock_cognee}):
            result = await memory_service.status()

        assert result["ready"] is True
        assert result["cognee_version"] == "0.5.1"

    @pytest.mark.asyncio
    async def test_status_not_ready(self, unready_service):
        result = await unready_service.status()
        assert result["ready"] is False
        assert "cognee_version" not in result


# ---------------------------------------------------------------------------
# CogneeMemoryService._safe_start — exception handling
# ---------------------------------------------------------------------------


class TestSafeStart:
    @pytest.mark.asyncio
    async def test_safe_start_catches_exception(self):
        svc = CogneeMemoryService()
        # Patch start to blow up
        with patch.object(svc, "start", side_effect=RuntimeError("import failed")):
            await svc._safe_start({})
        # Service must NOT be ready, and daemon must NOT crash
        assert svc._ready is False

    @pytest.mark.asyncio
    async def test_safe_start_success(self):
        svc = CogneeMemoryService()

        async def fake_start(config):
            svc._ready = True

        with patch.object(svc, "start", side_effect=fake_start):
            await svc._safe_start({"enabled": True})
        assert svc._ready is True


# ---------------------------------------------------------------------------
# CogneeMemoryService.stop
# ---------------------------------------------------------------------------


class TestStop:
    @pytest.mark.asyncio
    async def test_stop_sets_not_ready(self, memory_service):
        assert memory_service._ready is True
        await memory_service.stop()
        assert memory_service._ready is False


# ---------------------------------------------------------------------------
# CogneeMemoryService._get_api_key
# ---------------------------------------------------------------------------


class TestGetApiKey:
    def test_env_var_preferred(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test-123"}):
            assert CogneeMemoryService._get_api_key() == "sk-test-123"

    @patch("subprocess.run")
    def test_keychain_fallback(self, mock_run):
        import json as _json

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=_json.dumps({"claudeAiOauth": {"accessToken": "kc-token"}}).encode(),
        )
        with patch.dict("os.environ", {}, clear=True):
            # Remove ANTHROPIC_API_KEY if present
            import os

            os.environ.pop("ANTHROPIC_API_KEY", None)
            assert CogneeMemoryService._get_api_key() == "kc-token"

    @patch("subprocess.run")
    def test_returns_none_when_unavailable(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr=b"not found")
        with patch.dict("os.environ", {}, clear=True):
            import os

            os.environ.pop("ANTHROPIC_API_KEY", None)
            assert CogneeMemoryService._get_api_key() is None


# ---------------------------------------------------------------------------
# CommandHandlers — memory handlers (sync bridge over async)
# ---------------------------------------------------------------------------


class TestCommandHandlerMemory:
    """Test memory IPC command handlers bridging sync -> async."""

    @pytest.fixture
    def handler_setup(self):
        """Create CommandHandlers wired to a mock memory service + event loop."""
        from clarvis.core.command_handlers import CommandHandlers
        from clarvis.core.ipc import DaemonServer
        from clarvis.core.refresh_manager import RefreshManager
        from clarvis.core.session_tracker import SessionTracker
        from clarvis.core.state import StateStore
        from clarvis.services.whimsy_verb import WhimsyManager

        loop = asyncio.new_event_loop()

        # Start loop in a background thread
        import threading

        t = threading.Thread(target=loop.run_forever, daemon=True)
        t.start()

        state = StateStore()
        svc = CogneeMemoryService()
        svc._ready = True

        handlers = CommandHandlers(
            state=state,
            session_tracker=SessionTracker(state),
            refresh=MagicMock(spec=RefreshManager),
            whimsy=MagicMock(spec=WhimsyManager),
            command_server=MagicMock(spec=DaemonServer),
            token_usage_service_provider=lambda: None,
            voice_orchestrator_provider=lambda: None,
            memory_service_provider=lambda: svc,
            context_accumulator_provider=lambda: None,
            event_loop=loop,
        )

        yield handlers, svc, loop

        loop.call_soon_threadsafe(loop.stop)
        t.join(timeout=2)
        loop.close()

    def test_memory_add_via_handler(self, handler_setup):
        handlers, svc, loop = handler_setup
        mock_cognee = MagicMock()
        mock_cognee.add = AsyncMock()

        with patch.dict("sys.modules", {"cognee": mock_cognee}):
            result = handlers.memory_add("hello world", "test")

        assert result["status"] == "ok"
        assert result["bytes"] == len("hello world")

    def test_memory_status_via_handler(self, handler_setup):
        handlers, svc, loop = handler_setup
        mock_cognee = MagicMock()
        mock_cognee.__version__ = "0.5.0"

        with patch.dict("sys.modules", {"cognee": mock_cognee}):
            result = handlers.memory_status()

        assert result["ready"] is True

    def test_memory_add_not_ready(self, handler_setup):
        handlers, svc, loop = handler_setup
        svc._ready = False
        result = handlers.memory_add("data")
        assert result == {"error": "Memory service not available"}

    def test_memory_search_not_ready(self, handler_setup):
        handlers, svc, loop = handler_setup
        svc._ready = False
        result = handlers.memory_search("query")
        assert result == {"error": "Memory service not available"}

    def test_memory_cognify_not_ready(self, handler_setup):
        handlers, svc, loop = handler_setup
        svc._ready = False
        result = handlers.memory_cognify()
        assert result == {"error": "Memory service not available"}

    def test_check_in_via_handler(self, handler_setup):
        handlers, svc, loop = handler_setup

        # Wire up a mock accumulator
        mock_accumulator = MagicMock()
        mock_accumulator.get_pending.return_value = {
            "sessions": [{"project": "test-project", "session_id": "abc"}],
            "staged_items": [],
            "last_check_in": "2026-01-01T00:00:00",
        }
        handlers._context_accumulator_provider = lambda: mock_accumulator

        result = handlers.check_in()

        assert "sessions" in result
        assert result["sessions"][0]["project"] == "test-project"
        assert "relevant_memories" in result
        mock_accumulator.get_pending.assert_called_once()

    def test_handler_no_event_loop(self):
        """If event loop is None, memory handlers return an error."""
        from clarvis.core.command_handlers import CommandHandlers
        from clarvis.core.ipc import DaemonServer
        from clarvis.core.session_tracker import SessionTracker
        from clarvis.core.state import StateStore

        svc = CogneeMemoryService()
        svc._ready = True

        handlers = CommandHandlers(
            state=StateStore(),
            session_tracker=MagicMock(spec=SessionTracker),
            refresh=MagicMock(),
            whimsy=MagicMock(),
            command_server=MagicMock(spec=DaemonServer),
            token_usage_service_provider=lambda: None,
            voice_orchestrator_provider=lambda: None,
            memory_service_provider=lambda: svc,
            event_loop=None,
        )
        result = handlers.memory_add("data")
        assert result == {"error": "Event loop not available"}


# ===========================================================================
# MCP Memory Tools — in-memory Client tests
# ===========================================================================


@pytest.fixture
def mock_daemon_for_mcp():
    """Mock DaemonClient that routes memory IPC commands."""
    client = MagicMock()
    client.is_daemon_running.return_value = True

    def route_call(method, **kwargs):
        routes = {
            "ping": "pong",
            "memory_add": {
                "status": "ok",
                "dataset": kwargs.get("dataset", "clarvis"),
                "bytes": len(kwargs.get("data", "")),
            },
            "memory_search": [{"result": "test fact", "score": 0.95}],
            "memory_cognify": {"status": "ok", "dataset": kwargs.get("dataset", "clarvis")},
            "memory_status": {"ready": True, "cognee_version": "0.5.0"},
            "check_in": {
                "sessions_since_last": [
                    {"session_id": "abc123", "project": "clarvis", "summary": "Worked on memory tools"}
                ],
                "staged_items": [],
                "last_check_in": "2026-02-06T12:00:00+00:00",
            },
            # Standard routes needed by create_app
            "refresh_time": {"timestamp": "2026-02-06T12:00:00", "timezone": "America/New_York"},
            "get_weather": {"temperature": 32, "description": "clear", "wind_speed": 10, "city": "Boston"},
            "refresh_weather": {"temperature": 32, "description": "clear", "wind_speed": 10, "city": "Boston"},
            "get_token_usage": {"5h": {"used": 1000, "limit": 5000}},
        }
        return routes.get(method)

    client.call.side_effect = route_call
    return client


@pytest_asyncio.fixture
async def memory_mcp_client(mock_daemon_for_mcp):
    """In-memory MCP client for the memory sub-server only."""
    srv = create_memory_server(daemon_client=mock_daemon_for_mcp)
    async with Client(srv) as c:
        yield c


@pytest_asyncio.fixture
async def full_mcp_client(mock_daemon_for_mcp):
    """In-memory MCP client with full app (memory tools mounted)."""
    import clarvis.spotify_tools as st

    st._device_cache.update({"names": None, "ts": 0})
    mock_session = MagicMock()
    mock_session.run.return_value = {"status": "ok"}
    app = create_app(daemon_client=mock_daemon_for_mcp, get_session=lambda: mock_session)
    async with Client(app) as c:
        yield c


class TestMemoryToolSurface:
    """Verify memory tools are registered and discoverable."""

    @pytest.mark.asyncio
    async def test_memory_tools_registered_in_full_app(self, full_mcp_client):
        """Memory tools appear in the full app tool list."""
        tools = await full_mcp_client.list_tools()
        names = {t.name for t in tools}
        assert {"memory_add", "memory_search", "memory_cognify", "memory_status", "check_in"} <= names

    @pytest.mark.asyncio
    async def test_memory_tools_registered_in_sub_server(self, memory_mcp_client):
        """Memory tools appear in the standalone sub-server."""
        tools = await memory_mcp_client.list_tools()
        names = {t.name for t in tools}
        assert names == {"memory_add", "memory_search", "memory_cognify", "memory_status", "check_in"}

    @pytest.mark.asyncio
    async def test_ctx_not_leaked(self, memory_mcp_client):
        """ctx parameter should not appear in any tool schema."""
        tools = await memory_mcp_client.list_tools()
        for tool in tools:
            assert "ctx" not in tool.inputSchema.get("properties", {}), f"ctx leaked in {tool.name}"

    @pytest.mark.asyncio
    async def test_memory_tools_have_descriptions(self, memory_mcp_client):
        """All memory tool parameters should have descriptions (agent-friendly)."""
        tools = await memory_mcp_client.list_tools()
        param_tools = [t for t in tools if t.name.startswith("memory_")]
        for tool in param_tools:
            props = tool.inputSchema.get("properties", {})
            for param_name, param_schema in props.items():
                assert "description" in param_schema, f"Missing description for {tool.name}.{param_name}"


class TestMCPMemoryAdd:
    @pytest.mark.asyncio
    async def test_add_basic(self, memory_mcp_client, mock_daemon_for_mcp):
        result = await memory_mcp_client.call_tool("memory_add", {"data": "Test fact"})
        assert result.data["status"] == "ok"
        assert result.data["bytes"] == 9
        mock_daemon_for_mcp.call.assert_any_call("memory_add", data="Test fact", dataset="clarvis")

    @pytest.mark.asyncio
    async def test_add_custom_dataset(self, memory_mcp_client, mock_daemon_for_mcp):
        result = await memory_mcp_client.call_tool("memory_add", {"data": "Fact", "dataset": "custom"})
        assert result.data["status"] == "ok"
        mock_daemon_for_mcp.call.assert_any_call("memory_add", data="Fact", dataset="custom")

    @pytest.mark.asyncio
    async def test_add_daemon_error(self, mock_daemon_for_mcp):
        mock_daemon_for_mcp.call.side_effect = RuntimeError("cognee.add failed")
        srv = create_memory_server(daemon_client=mock_daemon_for_mcp)
        async with Client(srv) as c:
            result = await c.call_tool("memory_add", {"data": "test"})
            assert "error" in result.data


class TestMCPMemorySearch:
    @pytest.mark.asyncio
    async def test_search_basic(self, memory_mcp_client, mock_daemon_for_mcp):
        result = await memory_mcp_client.call_tool("memory_search", {"query": "auth fix"})
        assert isinstance(result.data, list)
        assert result.data[0]["result"] == "test fact"
        mock_daemon_for_mcp.call.assert_any_call(
            "memory_search", query="auth fix", search_type="GRAPH_COMPLETION", top_k=10
        )

    @pytest.mark.asyncio
    async def test_search_custom_params(self, memory_mcp_client, mock_daemon_for_mcp):
        await memory_mcp_client.call_tool(
            "memory_search",
            {"query": "test", "search_type": "SUMMARIES", "top_k": 5},
        )
        mock_daemon_for_mcp.call.assert_any_call("memory_search", query="test", search_type="SUMMARIES", top_k=5)


class TestMCPMemoryCognify:
    @pytest.mark.asyncio
    async def test_cognify_basic(self, memory_mcp_client, mock_daemon_for_mcp):
        result = await memory_mcp_client.call_tool("memory_cognify", {})
        assert result.data["status"] == "ok"
        mock_daemon_for_mcp.call.assert_any_call("memory_cognify", dataset="clarvis")

    @pytest.mark.asyncio
    async def test_cognify_custom_dataset(self, memory_mcp_client, mock_daemon_for_mcp):
        await memory_mcp_client.call_tool("memory_cognify", {"dataset": "music"})
        mock_daemon_for_mcp.call.assert_any_call("memory_cognify", dataset="music")


class TestMCPMemoryStatus:
    @pytest.mark.asyncio
    async def test_status(self, memory_mcp_client, mock_daemon_for_mcp):
        result = await memory_mcp_client.call_tool("memory_status", {})
        assert result.data["ready"] is True
        mock_daemon_for_mcp.call.assert_any_call("memory_status")


class TestMCPCheckIn:
    @pytest.mark.asyncio
    async def test_check_in_returns_json(self, memory_mcp_client, mock_daemon_for_mcp):
        result = await memory_mcp_client.call_tool("check_in", {})
        parsed = json.loads(result.data)
        assert "sessions_since_last" in parsed
        assert parsed["sessions_since_last"][0]["project"] == "clarvis"
        mock_daemon_for_mcp.call.assert_any_call("check_in")

    @pytest.mark.asyncio
    async def test_check_in_daemon_down(self):
        dead = MagicMock()
        dead.is_daemon_running.return_value = False
        srv = create_memory_server(daemon_client=dead)
        async with Client(srv) as c:
            result = await c.call_tool("check_in", {})
            parsed = json.loads(result.data)
            assert "error" in parsed
            assert "not running" in parsed["error"]


# ===========================================================================
# ContextAccumulator Tests
# ===========================================================================


class TestExtractProjectFromSlug:
    def test_absolute_path_slug(self):
        name, path = extract_project_from_slug("-Users-shepardxia-Desktop-clarvis")
        assert name == "clarvis"
        assert path == "/Users/shepardxia/Desktop/clarvis"

    def test_relative_path_slug(self):
        name, path = extract_project_from_slug("my-project")
        assert name == "project"
        assert path == "my/project"


class TestContextAccumulatorInit:
    def test_creates_state_dir(self, tmp_path):
        state_dir = tmp_path / "staging"
        ContextAccumulator(state_dir=str(state_dir))
        assert state_dir.exists()

    def test_loads_persisted_state(self, tmp_path):
        state_dir = tmp_path / "staging"
        state_dir.mkdir()
        state_file = state_dir / "state.json"
        state_file.write_text(
            json.dumps(
                {
                    "last_check_in": "2026-01-15T10:00:00+00:00",
                    "staged_items": [{"content": "test", "timestamp": "2026-01-15T10:30:00+00:00"}],
                }
            )
        )

        acc = ContextAccumulator(state_dir=str(state_dir))
        assert acc._last_check_in == datetime.fromisoformat("2026-01-15T10:00:00+00:00")
        assert len(acc._staged_items) == 1
        assert acc._staged_items[0]["content"] == "test"

    def test_handles_corrupt_state(self, tmp_path):
        state_dir = tmp_path / "staging"
        state_dir.mkdir()
        (state_dir / "state.json").write_text("not json")

        # Should not raise
        acc = ContextAccumulator(state_dir=str(state_dir))
        assert acc._staged_items == []


class TestContextAccumulatorAccumulate:
    def _make_session(self, tmp_path, project_slug, session_id, summary_text, mtime=None):
        """Helper to create a fake session directory structure."""
        session_dir = tmp_path / "projects" / project_slug / session_id / "session-memory"
        session_dir.mkdir(parents=True)
        summary = session_dir / "summary.md"
        summary.write_text(summary_text)
        if mtime is not None:
            os.utime(summary, (mtime, mtime))
        return summary

    def test_discovers_new_sessions(self, tmp_path):
        """Sessions with summary.md newer than watermark are discovered."""
        self._make_session(tmp_path, "-Users-test-myproject", "session-abc", "Fixed a bug in auth.")

        state_dir = tmp_path / "staging"
        acc = ContextAccumulator(state_dir=str(state_dir))
        acc._last_check_in = datetime(2020, 1, 1, tzinfo=timezone.utc)

        import clarvis.services.context_accumulator as mod

        original = mod.CLAUDE_PROJECTS_DIR
        mod.CLAUDE_PROJECTS_DIR = tmp_path / "projects"
        try:
            acc.accumulate()
        finally:
            mod.CLAUDE_PROJECTS_DIR = original

        assert len(acc._session_refs) == 1
        ref = acc._session_refs[0]
        assert ref["session_id"] == "session-abc"
        assert ref["project_name"] == "myproject"

    def test_skips_sessions_before_watermark(self, tmp_path):
        """Sessions older than watermark are not picked up."""
        old_ts = datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp()
        self._make_session(tmp_path, "-Users-test-old", "sess-old", "Old session", mtime=old_ts)

        state_dir = tmp_path / "staging"
        acc = ContextAccumulator(state_dir=str(state_dir))
        acc._last_check_in = datetime(2025, 1, 1, tzinfo=timezone.utc)

        import clarvis.services.context_accumulator as mod

        original = mod.CLAUDE_PROJECTS_DIR
        mod.CLAUDE_PROJECTS_DIR = tmp_path / "projects"
        try:
            acc.accumulate()
        finally:
            mod.CLAUDE_PROJECTS_DIR = original

        assert len(acc._session_refs) == 0

    def test_no_duplicate_sessions(self, tmp_path):
        """Calling accumulate twice does not duplicate session refs."""
        self._make_session(tmp_path, "-Users-test-proj", "sess-1", "Summary")

        state_dir = tmp_path / "staging"
        acc = ContextAccumulator(state_dir=str(state_dir))
        acc._last_check_in = datetime(2020, 1, 1, tzinfo=timezone.utc)

        import clarvis.services.context_accumulator as mod

        original = mod.CLAUDE_PROJECTS_DIR
        mod.CLAUDE_PROJECTS_DIR = tmp_path / "projects"
        try:
            acc.accumulate()
            acc.accumulate()
        finally:
            mod.CLAUDE_PROJECTS_DIR = original

        assert len(acc._session_refs) == 1

    def test_discovers_multiple_projects(self, tmp_path):
        """Sessions across multiple projects are all discovered."""
        self._make_session(tmp_path, "-Users-test-alpha", "sess-a", "Alpha work")
        self._make_session(tmp_path, "-Users-test-beta", "sess-b", "Beta work")

        state_dir = tmp_path / "staging"
        acc = ContextAccumulator(state_dir=str(state_dir))
        acc._last_check_in = datetime(2020, 1, 1, tzinfo=timezone.utc)

        import clarvis.services.context_accumulator as mod

        original = mod.CLAUDE_PROJECTS_DIR
        mod.CLAUDE_PROJECTS_DIR = tmp_path / "projects"
        try:
            acc.accumulate()
        finally:
            mod.CLAUDE_PROJECTS_DIR = original

        assert len(acc._session_refs) == 2
        projects = {ref["project_name"] for ref in acc._session_refs}
        assert projects == {"alpha", "beta"}

    def test_handles_missing_projects_dir(self, tmp_path):
        """No error when ~/.claude/projects doesn't exist."""
        state_dir = tmp_path / "staging"
        acc = ContextAccumulator(state_dir=str(state_dir))

        import clarvis.services.context_accumulator as mod

        original = mod.CLAUDE_PROJECTS_DIR
        mod.CLAUDE_PROJECTS_DIR = tmp_path / "nonexistent"
        try:
            acc.accumulate()  # Should not raise
        finally:
            mod.CLAUDE_PROJECTS_DIR = original

        assert acc._session_refs == []

    def test_skips_sessions_without_summary(self, tmp_path):
        """Sessions without a summary.md file are ignored."""
        session_dir = tmp_path / "projects" / "-Users-test-proj" / "sess-no-summary"
        session_dir.mkdir(parents=True)
        # No summary.md created

        state_dir = tmp_path / "staging"
        acc = ContextAccumulator(state_dir=str(state_dir))
        acc._last_check_in = datetime(2020, 1, 1, tzinfo=timezone.utc)

        import clarvis.services.context_accumulator as mod

        original = mod.CLAUDE_PROJECTS_DIR
        mod.CLAUDE_PROJECTS_DIR = tmp_path / "projects"
        try:
            acc.accumulate()
        finally:
            mod.CLAUDE_PROJECTS_DIR = original

        assert acc._session_refs == []


class TestContextAccumulatorGetPending:
    def test_returns_bundle_structure(self, tmp_path):
        state_dir = tmp_path / "staging"
        acc = ContextAccumulator(state_dir=str(state_dir))
        result = acc.get_pending()

        assert "sessions_since_last" in result
        assert "staged_items" in result
        assert "last_check_in" in result
        assert isinstance(result["sessions_since_last"], list)
        assert isinstance(result["staged_items"], list)

    def test_lazy_loads_summaries(self, tmp_path):
        """Summaries are read on get_pending, not during accumulate."""
        project_dir = tmp_path / "projects" / "-Users-test-proj"
        session_dir = project_dir / "sess-1" / "session-memory"
        session_dir.mkdir(parents=True)
        summary = session_dir / "summary.md"
        summary.write_text("# Bug fix\nFixed auth module.")

        state_dir = tmp_path / "staging"
        acc = ContextAccumulator(state_dir=str(state_dir))
        acc._last_check_in = datetime(2020, 1, 1, tzinfo=timezone.utc)

        import clarvis.services.context_accumulator as mod

        original = mod.CLAUDE_PROJECTS_DIR
        mod.CLAUDE_PROJECTS_DIR = tmp_path / "projects"
        try:
            acc.accumulate()
        finally:
            mod.CLAUDE_PROJECTS_DIR = original

        result = acc.get_pending()
        assert "Fixed auth module" in result["sessions_since_last"][0]["summary"]

    def test_handles_deleted_summary(self, tmp_path):
        """If summary file is deleted between accumulate and get_pending, gracefully handle."""
        state_dir = tmp_path / "staging"
        acc = ContextAccumulator(state_dir=str(state_dir))
        # Manually add a ref pointing to a non-existent file
        acc._session_refs.append(
            {
                "session_id": "gone",
                "project_name": "test",
                "project_path": "/test",
                "summary_path": str(tmp_path / "nonexistent.md"),
                "mtime": 0,
            }
        )

        result = acc.get_pending()
        assert result["sessions_since_last"][0]["summary"] == "(summary file not found)"


class TestContextAccumulatorStageItem:
    def test_stage_item_adds_to_pending(self, tmp_path):
        state_dir = tmp_path / "staging"
        acc = ContextAccumulator(state_dir=str(state_dir))

        acc.stage_item("Important fact about auth")
        result = acc.get_pending()

        assert len(result["staged_items"]) == 1
        assert result["staged_items"][0]["content"] == "Important fact about auth"
        assert "timestamp" in result["staged_items"][0]

    def test_stage_item_persists(self, tmp_path):
        state_dir = tmp_path / "staging"
        acc = ContextAccumulator(state_dir=str(state_dir))
        acc.stage_item("Persisted fact")

        # Create new accumulator from same state dir
        acc2 = ContextAccumulator(state_dir=str(state_dir))
        assert len(acc2._staged_items) == 1
        assert acc2._staged_items[0]["content"] == "Persisted fact"

    def test_multiple_staged_items(self, tmp_path):
        state_dir = tmp_path / "staging"
        acc = ContextAccumulator(state_dir=str(state_dir))

        acc.stage_item("Fact 1")
        acc.stage_item("Fact 2")
        acc.stage_item("Fact 3")

        result = acc.get_pending()
        assert len(result["staged_items"]) == 3


class TestContextAccumulatorMarkCheckedIn:
    def test_clears_state(self, tmp_path):
        state_dir = tmp_path / "staging"
        acc = ContextAccumulator(state_dir=str(state_dir))

        acc.stage_item("Will be cleared")
        acc._session_refs.append(
            {
                "session_id": "x",
                "project_name": "test",
                "project_path": "/test",
                "summary_path": "/tmp/s.md",
                "mtime": 0,
            }
        )

        before = acc._last_check_in
        acc.mark_checked_in()

        assert acc._last_check_in > before
        assert acc._staged_items == []
        assert acc._session_refs == []

    def test_persists_watermark(self, tmp_path):
        state_dir = tmp_path / "staging"
        acc = ContextAccumulator(state_dir=str(state_dir))
        acc.mark_checked_in()

        # Load fresh
        acc2 = ContextAccumulator(state_dir=str(state_dir))
        # Should be close to acc's watermark (within a second)
        delta = abs((acc2._last_check_in - acc._last_check_in).total_seconds())
        assert delta < 1.0

    def test_get_pending_empty_after_check_in(self, tmp_path):
        state_dir = tmp_path / "staging"
        acc = ContextAccumulator(state_dir=str(state_dir))

        acc.stage_item("Fact")
        acc.mark_checked_in()

        result = acc.get_pending()
        assert result["sessions_since_last"] == []
        assert result["staged_items"] == []
