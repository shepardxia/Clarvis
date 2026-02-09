"""Tests for CogneeMemoryService, memory MCP tools, ContextAccumulator, and command handlers."""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastmcp import Client

from clarvis.memory_tools import create_memory_server
from clarvis.server import create_app
from clarvis.services.cognee_memory import CogneeMemoryService
from clarvis.services.context_accumulator import (
    ContextAccumulator,
    _extract_preview,
    extract_project_from_slug,
)

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


# ===========================================================================
# MCP Memory Tools — in-memory Client tests
# ===========================================================================


@pytest.fixture
def mock_daemon_for_mcp():
    """Mock daemon object with memory_service, context_accumulator, and standard services."""
    daemon = MagicMock()

    # Standard daemon attributes needed by create_app tools
    daemon.state.get.side_effect = lambda key, default=None: {
        "weather": {"temperature": 32, "description": "clear", "wind_speed": 10, "city": "Boston"},
    }.get(key, default)
    daemon.refresh.refresh_weather.return_value = {
        "temperature": 32,
        "description": "clear",
        "wind_speed": 10,
        "city": "Boston",
    }
    daemon.refresh.refresh_time.return_value = {
        "timestamp": "2026-02-06T12:00:00",
        "timezone": "America/New_York",
    }
    daemon.token_usage_service = MagicMock()
    daemon.token_usage_service.get_usage.return_value = {"5h": {"used": 1000, "limit": 5000}}

    # Memory service (async methods)
    daemon.memory_service = MagicMock()
    daemon.memory_service._ready = True
    daemon.memory_service.add = AsyncMock(
        side_effect=lambda data, dataset="clarvis": {"status": "ok", "dataset": dataset, "bytes": len(data)}
    )
    daemon.memory_service.search = AsyncMock(return_value=[{"result": "test fact", "score": 0.95}])
    daemon.memory_service.cognify = AsyncMock(
        side_effect=lambda dataset="clarvis": {"status": "ok", "dataset": dataset}
    )
    daemon.memory_service.status = AsyncMock(return_value={"ready": True, "cognee_version": "0.5.0"})

    # Context accumulator
    daemon.context_accumulator = MagicMock()
    daemon.context_accumulator.get_pending.return_value = {
        "sessions_since_last": [
            {
                "session_id": "abc123",
                "project": "clarvis",
                "project_path": "/Users/test/clarvis",
                "timestamp": "2026-02-06T14:00:00+00:00",
                "preview": "U: fix the auth bug\nA: I'll look into the auth module.",
            }
        ],
        "staged_items": [],
        "last_check_in": "2026-02-06T12:00:00+00:00",
    }

    return daemon


@pytest_asyncio.fixture
async def memory_mcp_client(mock_daemon_for_mcp):
    """In-memory MCP client for the memory sub-server only."""
    srv = create_memory_server(daemon=mock_daemon_for_mcp)
    async with Client(srv) as c:
        yield c


@pytest_asyncio.fixture
async def full_mcp_client(mock_daemon_for_mcp):
    """In-memory MCP client with full app (memory tools mounted)."""
    import clarvis.spotify_tools as st

    st._device_cache.update({"names": None, "ts": 0})
    mock_session = MagicMock()
    mock_session.run.return_value = {"status": "ok"}
    app = create_app(daemon=mock_daemon_for_mcp, get_session=lambda: mock_session)
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
        data = json.loads(result.content[0].text)
        assert data["status"] == "ok"
        assert data["bytes"] == 9
        mock_daemon_for_mcp.memory_service.add.assert_awaited_with("Test fact", "shepard")

    @pytest.mark.asyncio
    async def test_add_custom_dataset(self, memory_mcp_client, mock_daemon_for_mcp):
        result = await memory_mcp_client.call_tool("memory_add", {"data": "Fact", "dataset": "custom"})
        data = json.loads(result.content[0].text)
        assert data["status"] == "ok"
        mock_daemon_for_mcp.memory_service.add.assert_awaited_with("Fact", "custom")

    @pytest.mark.asyncio
    async def test_add_service_error(self, mock_daemon_for_mcp):
        daemon = mock_daemon_for_mcp
        daemon.memory_service.add = AsyncMock(return_value={"error": "cognee.add failed"})
        srv = create_memory_server(daemon=daemon)
        async with Client(srv) as c:
            result = await c.call_tool("memory_add", {"data": "test"})
            data = json.loads(result.content[0].text)
            assert "error" in data


class TestMCPMemorySearch:
    @pytest.mark.asyncio
    async def test_search_basic(self, memory_mcp_client, mock_daemon_for_mcp):
        result = await memory_mcp_client.call_tool("memory_search", {"query": "auth fix"})
        data = json.loads(result.content[0].text)
        assert isinstance(data, list)
        assert data[0]["result"] == "test fact"
        mock_daemon_for_mcp.memory_service.search.assert_awaited_with("auth fix", "GRAPH_COMPLETION", 10, datasets=None)

    @pytest.mark.asyncio
    async def test_search_custom_params(self, memory_mcp_client, mock_daemon_for_mcp):
        await memory_mcp_client.call_tool(
            "memory_search",
            {"query": "test", "search_type": "SUMMARIES", "top_k": 5},
        )
        mock_daemon_for_mcp.memory_service.search.assert_awaited_with("test", "SUMMARIES", 5, datasets=None)


class TestMCPMemoryCognify:
    @pytest.mark.asyncio
    async def test_cognify_basic(self, memory_mcp_client, mock_daemon_for_mcp):
        result = await memory_mcp_client.call_tool("memory_cognify", {})
        data = json.loads(result.content[0].text)
        assert data["status"] == "ok"
        mock_daemon_for_mcp.memory_service.cognify.assert_awaited_with("shepard")

    @pytest.mark.asyncio
    async def test_cognify_custom_dataset(self, memory_mcp_client, mock_daemon_for_mcp):
        await memory_mcp_client.call_tool("memory_cognify", {"dataset": "music"})
        mock_daemon_for_mcp.memory_service.cognify.assert_awaited_with("music")


class TestMCPMemoryStatus:
    @pytest.mark.asyncio
    async def test_status(self, memory_mcp_client, mock_daemon_for_mcp):
        result = await memory_mcp_client.call_tool("memory_status", {})
        data = json.loads(result.content[0].text)
        assert data["ready"] is True


class TestMCPCheckIn:
    @pytest.mark.asyncio
    async def test_check_in_returns_json(self, memory_mcp_client, mock_daemon_for_mcp):
        result = await memory_mcp_client.call_tool("check_in", {})
        parsed = json.loads(result.data)
        assert "sessions_since_last" in parsed
        assert parsed["sessions_since_last"][0]["project"] == "clarvis"

    @pytest.mark.asyncio
    async def test_check_in_no_accumulator(self):
        daemon = MagicMock()
        daemon.memory_service = MagicMock()
        daemon.context_accumulator = None
        srv = create_memory_server(daemon=daemon)
        async with Client(srv) as c:
            result = await c.call_tool("check_in", {})
            parsed = json.loads(result.data)
            assert "error" in parsed
            assert "accumulator" in parsed["error"]


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


class TestExtractPreview:
    """Tests for _extract_preview JSONL transcript parsing."""

    def _make_transcript(self, tmp_path, lines):
        """Write JSONL lines to a transcript file."""
        tp = tmp_path / "-Users-test-proj" / "sess-1.jsonl"
        tp.parent.mkdir(parents=True, exist_ok=True)
        tp.write_text("\n".join(json.dumps(entry) for entry in lines))
        return str(tp)

    def test_extracts_user_and_assistant(self, tmp_path):
        path = self._make_transcript(
            tmp_path,
            [
                {"type": "user", "message": {"content": "fix the bug"}},
                {"type": "assistant", "message": {"content": "Looking into it."}},
            ],
        )
        preview = _extract_preview(path)
        assert "U: fix the bug" in preview
        assert "A: Looking into it." in preview

    def test_skips_system_reminders(self, tmp_path):
        path = self._make_transcript(
            tmp_path,
            [
                {"type": "user", "message": {"content": "hello"}},
                {"type": "assistant", "message": {"content": "<system-reminder>ignore</system-reminder>"}},
                {"type": "assistant", "message": {"content": "Hi there!"}},
            ],
        )
        preview = _extract_preview(path)
        assert "<system" not in preview
        assert "Hi there!" in preview

    def test_flattens_content_arrays(self, tmp_path):
        path = self._make_transcript(
            tmp_path,
            [
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "text", "text": "Here is the fix."},
                            {"type": "tool_use", "name": "Edit"},
                            {"type": "text", "text": "<system-reminder>skip</system-reminder>"},
                        ]
                    },
                },
            ],
        )
        preview = _extract_preview(path)
        assert "Here is the fix." in preview
        assert "Edit" not in preview
        assert "<system" not in preview

    def test_missing_file(self):
        assert _extract_preview("/nonexistent/path.jsonl") == "(transcript not found)"

    def test_empty_transcript(self, tmp_path):
        path = self._make_transcript(
            tmp_path,
            [
                {"type": "summary", "content": "compacted"},
            ],
        )
        preview = _extract_preview(path)
        assert preview == "(empty session)"

    def test_limits_messages(self, tmp_path):
        """Only last N messages are extracted."""
        lines = [{"type": "user", "message": {"content": f"msg {i}"}} for i in range(20)]
        path = self._make_transcript(tmp_path, lines)
        preview = _extract_preview(path)
        # Should have at most _PREVIEW_MESSAGES lines
        assert preview.count("\n") <= 7  # 8 messages = 7 newlines

    def test_truncates_long_messages(self, tmp_path):
        path = self._make_transcript(
            tmp_path,
            [
                {"type": "user", "message": {"content": "x" * 500}},
            ],
        )
        preview = _extract_preview(path)
        assert len(preview.split(": ", 1)[1]) <= 300


class TestContextAccumulatorStageSession:
    def test_stages_session(self, tmp_path):
        state_dir = tmp_path / "staging"
        acc = ContextAccumulator(state_dir=str(state_dir))

        tp = tmp_path / "-Users-test-myproject" / "sess-abc.jsonl"
        tp.parent.mkdir(parents=True)
        tp.write_text("")

        acc.stage_session("sess-abc", str(tp))

        assert len(acc._session_refs) == 1
        ref = acc._session_refs[0]
        assert ref["session_id"] == "sess-abc"
        assert ref["project_name"] == "myproject"
        assert ref["transcript_path"] == str(tp)

    def test_deduplicates(self, tmp_path):
        state_dir = tmp_path / "staging"
        acc = ContextAccumulator(state_dir=str(state_dir))

        tp = tmp_path / "-Users-test-proj" / "sess-1.jsonl"
        tp.parent.mkdir(parents=True)
        tp.write_text("")

        acc.stage_session("sess-1", str(tp))
        acc.stage_session("sess-1", str(tp))

        assert len(acc._session_refs) == 1

    def test_persists_session_refs(self, tmp_path):
        state_dir = tmp_path / "staging"
        acc = ContextAccumulator(state_dir=str(state_dir))

        tp = tmp_path / "-Users-test-proj" / "sess-x.jsonl"
        tp.parent.mkdir(parents=True)
        tp.write_text("")

        acc.stage_session("sess-x", str(tp))

        # Reload from disk
        acc2 = ContextAccumulator(state_dir=str(state_dir))
        assert len(acc2._session_refs) == 1
        assert acc2._session_refs[0]["session_id"] == "sess-x"

    def test_multiple_projects(self, tmp_path):
        state_dir = tmp_path / "staging"
        acc = ContextAccumulator(state_dir=str(state_dir))

        for slug, sid in [("-Users-test-alpha", "s1"), ("-Users-test-beta", "s2")]:
            tp = tmp_path / slug / f"{sid}.jsonl"
            tp.parent.mkdir(parents=True, exist_ok=True)
            tp.write_text("")
            acc.stage_session(sid, str(tp))

        assert len(acc._session_refs) == 2
        projects = {ref["project_name"] for ref in acc._session_refs}
        assert projects == {"alpha", "beta"}


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

    def test_extracts_preview_from_transcript(self, tmp_path):
        """Previews are extracted lazily from JSONL transcripts."""
        tp = tmp_path / "-Users-test-proj" / "sess-1.jsonl"
        tp.parent.mkdir(parents=True)
        tp.write_text(
            json.dumps({"type": "user", "message": {"content": "fix auth bug"}})
            + "\n"
            + json.dumps({"type": "assistant", "message": {"content": "On it."}})
        )

        state_dir = tmp_path / "staging"
        acc = ContextAccumulator(state_dir=str(state_dir))
        acc.stage_session("sess-1", str(tp))

        result = acc.get_pending()
        preview = result["sessions_since_last"][0]["preview"]
        assert "fix auth bug" in preview
        assert "On it." in preview

    def test_handles_missing_transcript(self, tmp_path):
        state_dir = tmp_path / "staging"
        acc = ContextAccumulator(state_dir=str(state_dir))
        acc._session_refs.append(
            {
                "session_id": "gone",
                "project_name": "test",
                "project_path": "/test",
                "transcript_path": str(tmp_path / "nonexistent.jsonl"),
                "timestamp": "2026-01-01T00:00:00+00:00",
            }
        )

        result = acc.get_pending()
        assert result["sessions_since_last"][0]["preview"] == "(transcript not found)"


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
                "transcript_path": "/tmp/s.jsonl",
                "timestamp": "2026-01-01T00:00:00+00:00",
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
