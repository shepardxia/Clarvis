"""Tests for ctools daemon commands (IPC handlers for agent CLI)."""

import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def loop():
    """Background-thread event loop (same pattern as test_mcp.py)."""
    _loop = asyncio.new_event_loop()
    t = threading.Thread(target=_loop.run_forever, daemon=True)
    t.start()
    yield _loop
    _loop.call_soon_threadsafe(_loop.stop)
    t.join(timeout=2)
    _loop.close()


@pytest.fixture
def mock_store():
    store = MagicMock()
    store.ready = True
    store.recall = AsyncMock(
        return_value={"results": [{"text": "likes dark roast coffee", "score": 0.9, "fact_type": "world"}]}
    )
    store.store_facts = AsyncMock(return_value=["id-1"])
    store.update_fact = AsyncMock(return_value={"success": True, "old_id": "x", "new_ids": ["y"]})
    store.delete_fact = AsyncMock(return_value={})
    store.list_facts = AsyncMock(return_value={"items": [], "total": 0})
    store.get_bank_stats = AsyncMock(return_value={"fact_count": 42})
    store.list_mental_models = AsyncMock(return_value=[])
    store.search_mental_models = AsyncMock(return_value={"results": []})
    store.create_mental_model = AsyncMock(return_value={"id": "mm-1"})
    store.update_mental_model = AsyncMock(return_value={})
    store.delete_mental_model = AsyncMock(return_value={})
    store.list_observations = AsyncMock(return_value=[])
    store.get_observation = AsyncMock(return_value={"content": "test obs"})
    store.get_unconsolidated = AsyncMock(return_value={"facts": []})
    store.get_fact = AsyncMock(return_value={"text": "a fact", "tags": ["t"]})
    store.get_related_observations = AsyncMock(return_value={"observations": []})
    store.apply_consolidation_decisions = AsyncMock(return_value={"created": 1})
    store.list_models_needing_refresh = AsyncMock(return_value=[])
    store.list_directives = AsyncMock(return_value=[])
    store.create_directive = AsyncMock(return_value={"id": "d-1"})
    store.update_directive = AsyncMock(return_value={})
    store.delete_directive = AsyncMock(return_value={})
    store.get_bank_profile = AsyncMock(return_value={"mission": "test"})
    store.set_bank_mission = AsyncMock(return_value={})
    store.update_bank_disposition = AsyncMock(return_value={})
    return store


@pytest.fixture
def mock_cognee():
    backend = MagicMock()
    backend.ready = True
    backend.search = AsyncMock(return_value=[{"result": "test"}])
    backend.ingest = AsyncMock(return_value={"status": "ok"})
    backend.list_entities = AsyncMock(return_value=[])
    backend.list_facts = AsyncMock(return_value=[])
    backend.update_entity = AsyncMock(return_value={"status": "ok", "updated_fields": ["name"]})
    backend.merge_entities = AsyncMock(return_value={"status": "ok", "merged_count": 1})
    backend.delete = AsyncMock(return_value={"deleted_id": "x"})
    backend.build_communities = AsyncMock(return_value={"status": "ok"})
    return backend


def _make_handlers(loop, **services):
    """Helper: create CommandHandlers with a running loop and given services."""
    from clarvis.core.command_handlers import CommandHandlers

    ctx = MagicMock()
    ctx.loop = loop
    ctx.bus = MagicMock()
    ctx.state = MagicMock()
    ctx.config = {}

    return CommandHandlers(
        ctx=ctx,
        session_tracker=MagicMock(),
        refresh=MagicMock(),
        command_server=MagicMock(),
        services=services,
    )


@pytest.fixture
def handlers(loop, mock_store, mock_cognee):
    return _make_handlers(
        loop,
        hindsight_store=lambda: mock_store,
        cognee_backend=lambda: mock_cognee,
    )


# ── Memory: facts ──────────────────────────────────────────────────


class TestRecallCommand:
    def test_recall_returns_results(self, handlers, mock_store):
        result = handlers.recall_memory(query="coffee preferences")
        assert "dark roast coffee" in result
        mock_store.recall.assert_called_once()

    def test_recall_passes_bank(self, handlers, mock_store):
        handlers.recall_memory(query="test", bank="agora")
        mock_store.recall.assert_called_once_with("test", bank="agora", fact_type=None, tags=None)

    def test_recall_requires_query(self, handlers):
        with pytest.raises(TypeError):
            handlers.recall_memory()

    def test_recall_when_store_not_ready(self, handlers, mock_store):
        mock_store.ready = False
        result = handlers.recall_memory(query="test")
        assert result == {"error": "Memory not available"}

    def test_recall_when_no_store(self, loop):
        h = _make_handlers(loop)
        result = h.recall_memory(query="test")
        assert result == {"error": "Memory not available"}


class TestRememberCommand:
    def test_remember_stores_fact(self, handlers, mock_store):
        result = handlers.remember_fact(text="prefers dark roast coffee")
        assert "Stored" in result
        assert "id-1" in result
        mock_store.store_facts.assert_called_once()

    def test_remember_defaults_to_world_type(self, handlers, mock_store):
        handlers.remember_fact(text="some fact")
        facts = mock_store.store_facts.call_args[0][0]
        assert facts[0].fact_type == "world"

    def test_remember_requires_text(self, handlers):
        with pytest.raises(TypeError):
            handlers.remember_fact()


class TestFactCRUD:
    def test_update_fact(self, handlers, mock_store):
        result = handlers.update_fact(fact_id="abc", content="updated text")
        assert "Updated" in result
        mock_store.update_fact.assert_called_once()

    def test_forget(self, handlers, mock_store):
        result = handlers.forget(fact_id="abc")
        assert "Forgotten" in result
        mock_store.delete_fact.assert_called_once_with("abc")

    def test_list_facts(self, handlers, mock_store):
        result = handlers.list_facts(bank="parletre")
        assert "No memories found" in result
        mock_store.list_facts.assert_called_once()


# ── Memory: stats & audit ──────────────────────────────────────────


class TestStatsAndAudit:
    def test_stats(self, handlers, mock_store):
        result = handlers.stats(bank="parletre")
        assert "fact_count: 42" in result

    def test_audit_returns_all_categories(self, handlers, mock_store):
        result = handlers.audit()
        assert "Facts since" in result
        assert "Observations since" in result
        assert "Mental models since" in result


# ── Memory: mental models ──────────────────────────────────────────


class TestMentalModels:
    def test_create_model(self, handlers, mock_store):
        result = handlers.create_model(name="Test", content="body", source_query="q")
        assert "Created mental model 'Test'" in result
        assert "mm-1" in result


# ── Memory: observations & consolidation ───────────────────────────


class TestObservations:
    def test_get_observation(self, handlers, mock_store):
        result = handlers.get_observation(id="obs-1")
        assert "test obs" in result

    def test_related_observations(self, handlers, mock_store):
        """Verifies N+1 fact lookup and aggregation into related_observations call."""
        handlers.related_observations(fact_ids=["f1", "f2"])
        assert mock_store.get_fact.call_count == 2
        mock_store.get_related_observations.assert_called_once()

    def test_consolidate(self, handlers, mock_store):
        result = handlers.consolidate(
            decisions=[{"action": "create", "text": "obs text", "source_fact_ids": ["f1"]}],
            fact_ids_to_mark=["f1"],
        )
        assert "1 created" in result

    def test_consolidate_invalid_decisions(self, handlers):
        result = handlers.consolidate(decisions=[{"bad": "data"}], fact_ids_to_mark=[])
        assert "error" in result


# ── Memory: directives ─────────────────────────────────────────────


class TestDirectives:
    def test_create_directive(self, handlers, mock_store):
        result = handlers.create_directive(name="No hardcoded paths", content="Always derive paths")
        assert "Created directive 'No hardcoded paths'" in result
        assert "d-1" in result


# ── Memory: bank profile ──────────────────────────────────────────


class TestBankProfile:
    def test_get_profile(self, handlers, mock_store):
        result = handlers.get_profile()
        assert "mission: test" in result


# ── Knowledge graph (Cognee) ───────────────────────────────────────


class TestKnowledge:
    def test_knowledge_search(self, handlers, mock_cognee):
        result = handlers.knowledge(query="test")
        assert "Results (1)" in result

    def test_ingest(self, handlers, mock_cognee):
        result = handlers.ingest(content_or_path="some text")
        assert "Ingested" in result
        assert "status: ok" in result

    def test_merge_entities_requires_two(self, handlers):
        result = handlers.merge_entities(entity_ids=["e1"])
        assert "error" in result

    def test_knowledge_when_no_backend(self, loop):
        h = _make_handlers(loop)
        result = h.knowledge(query="test")
        assert result == {"error": "Knowledge service not available"}


# ── Spotify ────────────────────────────────────────────────────────


class TestSpotifyCommand:
    @pytest.fixture
    def spotify_handlers(self, loop):
        mock_session = MagicMock()
        mock_session.run = MagicMock(return_value={"status": "playing", "track": "jazz"})
        h = _make_handlers(loop, spotify_session=lambda: mock_session)
        return h, mock_session

    def test_spotify_runs_dsl_command(self, spotify_handlers):
        h, mock_session = spotify_handlers
        result = h.spotify(command='play "jazz" volume 70')
        assert isinstance(result, str)
        mock_session.run.assert_called_once_with('play "jazz" volume 70')

    def test_spotify_requires_command(self, spotify_handlers):
        h, _ = spotify_handlers
        with pytest.raises(TypeError):
            h.spotify()

    def test_spotify_when_no_session(self, loop):
        h = _make_handlers(loop)
        result = h.spotify(command="play jazz")
        assert result == {"error": "Spotify not available"}

    def test_spotify_catches_dsl_error(self, spotify_handlers):
        h, mock_session = spotify_handlers
        mock_session.run.side_effect = Exception("No active device")
        result = h.spotify(command="play jazz")
        assert "No active device" in result["error"]


# ── Timers ─────────────────────────────────────────────────────────


class TestTimerCommand:
    @pytest.fixture
    def timer_handlers(self, loop):
        mock_timer = MagicMock()
        timer_result = MagicMock()
        timer_result.name = "checkin"
        timer_result.duration = 7200.0
        timer_result.fire_at = 1000007200.0
        mock_timer.set_timer = MagicMock(return_value=timer_result)
        mock_timer.list_timers = MagicMock(return_value=[])
        mock_timer.cancel = MagicMock(return_value=True)
        h = _make_handlers(loop, timer_service=lambda: mock_timer)
        return h, mock_timer

    def test_timer_set(self, timer_handlers):
        h, mock_timer = timer_handlers
        result = h.timer(action="set", name="checkin", duration="2h")
        mock_timer.set_timer.assert_called_once_with("checkin", 7200.0, False, "", False)
        assert "Timer 'checkin' set" in result

    def test_timer_list(self, timer_handlers):
        h, mock_timer = timer_handlers
        result = h.timer(action="list")
        mock_timer.list_timers.assert_called_once()
        assert "No active timers" in result

    def test_timer_cancel(self, timer_handlers):
        h, mock_timer = timer_handlers
        result = h.timer(action="cancel", name="checkin")
        mock_timer.cancel.assert_called_once_with("checkin")
        assert "Cancelled timer 'checkin'" in result

    def test_timer_requires_action(self, timer_handlers):
        h, _ = timer_handlers
        with pytest.raises(TypeError):
            h.timer()

    def test_timer_unknown_action(self, timer_handlers):
        h, _ = timer_handlers
        result = h.timer(action="explode")
        assert result == {"error": "Unknown action: explode"}

    def test_timer_when_no_service(self, loop):
        h = _make_handlers(loop)
        result = h.timer(action="list")
        assert result == {"error": "Timer service not available"}


# ── Channels ───────────────────────────────────────────────────────


class TestChannels:
    def test_get_channels_when_no_manager(self, loop):
        h = _make_handlers(loop)
        result = h.get_channels()
        assert result == {"error": "Channel manager not available"}


# ── Core tools ─────────────────────────────────────────────────────


class TestCoreTools:
    def test_stage_memory(self, handlers, tmp_path, monkeypatch):
        monkeypatch.setattr("clarvis.core.command_handlers._STAGING_DIR", tmp_path)
        result = handlers.stage_memory(summary="test session summary")
        assert result["queued"] == 1

    def test_prompt_response(self, handlers):
        result = handlers.prompt_response()
        assert result["status"] == "listening"
