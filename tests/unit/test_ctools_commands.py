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
def mock_memory():
    """Unified MemoryStore mock — covers both fact (Hindsight) and KG (Cognee) methods."""
    store = MagicMock()
    store.ready = True
    # Hindsight fact methods
    store.recall = AsyncMock(
        return_value={"results": [{"text": "likes dark roast coffee", "score": 0.9, "fact_type": "world"}]}
    )
    store.store_facts = AsyncMock(return_value=["id-1"])
    store.update_fact = AsyncMock(return_value={"success": True, "fact_id": "abc"})
    store.delete_fact = AsyncMock(return_value={})
    store.list_facts = AsyncMock(return_value={"items": [], "total": 0})
    store.get_bank_stats = AsyncMock(return_value={"fact_count": 42})
    store.list_mental_models = AsyncMock(return_value=[])
    store.search_mental_models = AsyncMock(return_value={"mental_models": [], "count": 0})
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
    # Knowledge graph methods
    store.kg_search = AsyncMock(return_value="Results (1):\n  1. test result")
    store.kg_ingest = AsyncMock(return_value="Ingested into 'knowledge' (status: ok)")
    store.kg_list_entities = AsyncMock(return_value="No entities found.")
    store.kg_list_relations = AsyncMock(return_value="No relationships found.")
    store.kg_update_entity = AsyncMock(return_value="Updated entity abcdef123456: name")
    store.kg_merge_entities = AsyncMock(return_value="Merged 1 entities into abcdef123456")
    store.kg_delete_entity = AsyncMock(return_value="Deleted: abcdef123456")
    store.kg_build_communities = AsyncMock(return_value="Community summaries built (status: ok)")
    return store


def _make_handlers(loop, **services):
    """Helper: create CommandHandlers with a running loop and given services."""
    from clarvis.core.commands import CommandHandlers

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
def handlers(loop, mock_memory):
    return _make_handlers(
        loop,
        memory=lambda: mock_memory,
    )


# ── Memory: facts ──────────────────────────────────────────────────


class TestRecallCommand:
    def test_recall_returns_results(self, handlers, mock_memory):
        result = handlers.recall_memory(query="coffee preferences")
        assert "dark roast coffee" in result
        mock_memory.recall.assert_called_once()

    def test_recall_passes_bank(self, handlers, mock_memory):
        handlers.recall_memory(query="test", bank="agora")
        mock_memory.recall.assert_called_once_with("test", bank="agora", fact_type=None, tags=None)

    def test_recall_requires_query(self, handlers):
        with pytest.raises(TypeError):
            handlers.recall_memory()

    def test_recall_when_store_not_ready(self, handlers, mock_memory):
        mock_memory.ready = False
        result = handlers.recall_memory(query="test")
        assert result == {"error": "Memory not available"}

    def test_recall_limit(self, handlers, mock_memory):
        """limit= truncates results after retrieval."""
        mock_memory.recall = AsyncMock(
            return_value={"results": [{"text": f"fact-{i}", "score": 0.9, "fact_type": "world"} for i in range(20)]}
        )
        result = handlers.recall_memory(query="test", limit=5)
        # Should only show 5 facts, not 20
        assert result.count("[world]") == 5

    def test_recall_when_no_store(self, loop):
        h = _make_handlers(loop)
        result = h.recall_memory(query="test")
        assert result == {"error": "Memory not available"}


class TestRememberCommand:
    def test_remember_stores_fact(self, handlers, mock_memory):
        result = handlers.remember_fact(text="prefers dark roast coffee")
        assert "Stored" in result
        assert "id-1" in result
        mock_memory.store_facts.assert_called_once()

    def test_remember_defaults_to_world_type(self, handlers, mock_memory):
        handlers.remember_fact(text="some fact")
        facts = mock_memory.store_facts.call_args[0][0]
        assert facts[0].fact_type == "world"

    def test_remember_requires_text(self, handlers):
        with pytest.raises(TypeError):
            handlers.remember_fact()


class TestFactCRUD:
    def test_update_fact(self, handlers, mock_memory):
        result = handlers.update_fact(id="abc", text="updated text")
        assert "Updated" in result
        mock_memory.update_fact.assert_called_once()

    def test_forget(self, handlers, mock_memory):
        result = handlers.forget(id="abc")
        assert "Forgotten" in result
        mock_memory.delete_fact.assert_called_once_with("abc")

    def test_list_facts(self, handlers, mock_memory):
        result = handlers.list_facts(bank="parletre")
        assert "No memories found" in result
        mock_memory.list_facts.assert_called_once()

    def test_get_fact(self, handlers, mock_memory):
        mock_memory.get_fact = AsyncMock(
            return_value={
                "id": "f1",
                "text": "likes jazz",
                "fact_type": "opinion",
                "confidence": 0.9,
                "tags": ["music"],
                "consolidated_at": None,
            }
        )
        result = handlers.get_fact(id="f1")
        assert "likes jazz" in result
        assert "opinion" in result
        assert "0.9" in result
        assert "music" in result
        assert "bank:parletre" in result
        assert "Consolidated: no" in result

    def test_get_fact_not_found(self, handlers, mock_memory):
        mock_memory.get_fact = AsyncMock(return_value=None)
        result = handlers.get_fact(id="nonexistent")
        assert "not found" in result

    def test_recall_shows_bank(self, handlers, mock_memory):
        """Recall output should include the bank tag for disambiguation."""
        result = handlers.recall_memory(query="coffee", bank="agora")
        assert "[agora]" in result

    def test_list_facts_shows_bank(self, handlers, mock_memory):
        """List facts output should include bank tag."""
        mock_memory.list_facts = AsyncMock(
            return_value={"items": [{"id": "f1", "text": "a fact", "fact_type": "world"}], "total": 1}
        )
        result = handlers.list_facts(bank="agora")
        assert "[agora]" in result


# ── Memory: stats & audit ──────────────────────────────────────────


class TestStatsAndAudit:
    def test_stats(self, handlers, mock_memory):
        result = handlers.stats(bank="parletre")
        assert "fact_count: 42" in result

    def test_audit_returns_all_categories(self, handlers, mock_memory):
        result = handlers.audit()
        assert "Facts since" in result
        assert "Observations since" in result
        assert "Mental models since" in result


# ── Memory: mental models ──────────────────────────────────────────


class TestMentalModels:
    def test_search_models_tags_match(self, handlers, mock_memory):
        """tags_match parameter should be passed through to the store."""
        mock_memory.search_mental_models.return_value = {
            "mental_models": [{"id": "mm-1", "name": "Test", "content": "body", "tags": ["music"]}],
            "count": 1,
        }
        handlers.search_models(query="test", tags=["music", "people"], tags_match="all")
        mock_memory.search_mental_models.assert_called_once_with(
            "test", bank="parletre", tags=["music", "people"], tags_match="all"
        )

    def test_search_models_empty_with_tags_diagnoses(self, handlers, mock_memory):
        """When tags narrow to zero, a follow-up query-only search diagnoses the cause."""
        mock_memory.search_mental_models.side_effect = [
            {"mental_models": [], "count": 0},  # first call: query + tags
            {"mental_models": [{"id": "mm-1", "name": "M"}], "count": 1},  # follow-up: query only
        ]
        result = handlers.search_models(query="test", tags=["nonexistent"])
        assert "matched the query alone" in result
        assert mock_memory.search_mental_models.call_count == 2

    def test_create_model(self, handlers, mock_memory):
        result = handlers.create_model(name="Test", content="body", source_query="q")
        assert "Created mental model 'Test'" in result
        assert "mm-1" in result


# ── Memory: observations & consolidation ───────────────────────────


class TestObservations:
    def test_get_observation(self, handlers, mock_memory):
        result = handlers.get_observation(id="obs-1")
        assert "test obs" in result

    def test_get_observation_shows_text_key(self, handlers, mock_memory):
        """Engine returns 'text' key — verify it surfaces in get_observation output."""
        mock_memory.get_observation = AsyncMock(
            return_value={"id": "obs-1", "text": "observation via text key", "tags": ["t1"]}
        )
        result = handlers.get_observation(id="obs-1")
        assert "observation via text key" in result

    def test_list_observations_shows_text_content(self, handlers, mock_memory):
        """Engine returns 'text' key — verify fmt_observations surfaces it."""
        mock_memory.list_observations = AsyncMock(
            return_value=[
                {"id": "obs-1", "text": "first obs text", "tags": [], "source_memory_ids": ["f1", "f2"]},
                {"id": "obs-2", "text": "second obs text", "tags": ["tag1"], "source_memory_ids": []},
            ]
        )
        result = handlers.list_observations()
        assert "first obs text" in result
        assert "second obs text" in result
        assert "2 sources" in result

    def test_related_observations(self, handlers, mock_memory):
        """Verifies N+1 fact lookup and aggregation into related_observations call."""
        handlers.related_observations(fact_ids=["f1", "f2"])
        assert mock_memory.get_fact.call_count == 2
        mock_memory.get_related_observations.assert_called_once()

    def test_consolidate_create_only(self, handlers, mock_memory):
        """Create-only decisions should NOT fetch observations (no need for validation)."""
        result = handlers.consolidate(
            decisions=[{"action": "create", "text": "obs text", "source_fact_ids": ["f1"]}],
            fact_ids_to_mark=["f1"],
        )
        assert "1 created" in result
        mock_memory.list_observations.assert_not_called()

    def test_consolidate_update_fetches_related_observations(self, handlers, mock_memory):
        """Update decisions must auto-fetch observations so valid_obs_ids is populated."""
        mock_memory.list_observations = AsyncMock(return_value=[{"id": "obs-1", "text": "existing obs", "tags": []}])
        mock_memory.apply_consolidation_decisions = AsyncMock(
            return_value={"created": 0, "updated": 1, "deleted": 0, "marked": 1}
        )
        result = handlers.consolidate(
            decisions=[{"action": "update", "text": "revised", "observation_id": "obs-1", "source_fact_ids": ["f2"]}],
            fact_ids_to_mark=["f2"],
        )
        assert "1 updated" in result
        mock_memory.list_observations.assert_called_once()
        # Verify related_observations was passed (not None)
        call_kwargs = mock_memory.apply_consolidation_decisions.call_args
        assert call_kwargs.kwargs.get("related_observations") is not None

    def test_consolidate_delete_fetches_related_observations(self, handlers, mock_memory):
        """Delete decisions also need observation fetch for validation."""
        mock_memory.list_observations = AsyncMock(return_value=[{"id": "obs-1", "text": "to delete", "tags": []}])
        mock_memory.apply_consolidation_decisions = AsyncMock(
            return_value={"created": 0, "updated": 0, "deleted": 1, "marked": 0}
        )
        result = handlers.consolidate(
            decisions=[{"action": "delete", "observation_id": "obs-1"}],
            fact_ids_to_mark=[],
        )
        assert "1 deleted" in result
        mock_memory.list_observations.assert_called_once()

    def test_consolidate_observation_dict_to_memoryfact(self):
        """Verify list_observations output can be converted to MemoryFact for apply_consolidation_decisions.

        This is the exact shape returned by MemoryStore.list_observations() — the conversion
        must add fact_type='observation' and map source_memory_ids → source_fact_ids.
        """
        from hindsight_api.engine.response_models import MemoryFact

        # Real shape from list_observations (both SQL branch and engine branch)
        obs_dict = {
            "id": "e0852599-28dd-4a6b-bd71-7f1f051abd32",
            "bank_id": "parletre",
            "text": "Sinthome comrades known as of early 2026",
            "proof_count": 3,
            "history": [],
            "tags": ["people"],
            "source_memory_ids": ["f1-uuid", "f2-uuid", "f3-uuid"],
            "source_memories": [],
            "created_at": "2026-03-10T12:00:00+00:00",
            "updated_at": "2026-03-10T14:00:00+00:00",
        }
        enriched = {**obs_dict, "fact_type": "observation"}
        if "source_memory_ids" in enriched:
            enriched.setdefault("source_fact_ids", enriched.pop("source_memory_ids"))
        obj = MemoryFact(**enriched)
        assert str(obj.id) == obs_dict["id"]
        assert obj.fact_type == "observation"
        assert obj.text == obs_dict["text"]
        assert obj.source_fact_ids == ["f1-uuid", "f2-uuid", "f3-uuid"]
        assert obj.tags == ["people"]

    def test_consolidate_auto_derives_mark_ids(self, handlers, mock_memory):
        """When fact_ids_to_mark is omitted, auto-derive from decisions' source_fact_ids."""
        mock_memory.apply_consolidation_decisions = AsyncMock(
            return_value={"created": 1, "updated": 0, "deleted": 0, "marked": 2}
        )
        result = handlers.consolidate(
            decisions=[
                {"action": "create", "text": "obs1", "source_fact_ids": ["f1", "f2"]},
                {"action": "create", "text": "obs2", "source_fact_ids": ["f2", "f3"]},
            ],
        )
        assert "created" in result
        # Verify the auto-derived set {f1, f2, f3} was passed
        call_args = mock_memory.apply_consolidation_decisions.call_args
        mark_ids = call_args[0][2]  # positional arg: fact_ids_to_mark
        assert set(mark_ids) == {"f1", "f2", "f3"}

    def test_consolidate_explicit_mark_ids_override(self, handlers, mock_memory):
        """Explicit fact_ids_to_mark should be used as-is, not auto-derived."""
        mock_memory.apply_consolidation_decisions = AsyncMock(
            return_value={"created": 1, "updated": 0, "deleted": 0, "marked": 1}
        )
        result = handlers.consolidate(
            decisions=[{"action": "create", "text": "obs", "source_fact_ids": ["f1", "f2"]}],
            fact_ids_to_mark=["f1"],
        )
        assert "created" in result
        call_args = mock_memory.apply_consolidation_decisions.call_args
        mark_ids = call_args[0][2]
        assert mark_ids == ["f1"]

    def test_consolidate_invalid_decisions(self, handlers):
        result = handlers.consolidate(decisions=[{"bad": "data"}])
        assert "error" in result


# ── Knowledge graph (Cognee) ───────────────────────────────────────


class TestKnowledge:
    def test_knowledge_search(self, handlers, mock_memory):
        result = handlers.knowledge(query="test")
        assert "Results (1)" in result

    def test_ingest(self, handlers, mock_memory):
        result = handlers.ingest(content_or_path="some text")
        assert "Ingested" in result
        assert "status: ok" in result

    def test_merge_entities_requires_two(self, handlers, mock_memory):
        mock_memory.kg_merge_entities = AsyncMock(return_value="Error: need at least 2 entity IDs to merge")
        result = handlers.merge_entities(entity_ids=["e1"])
        assert "Error" in result

    def test_knowledge_when_no_backend(self, loop):
        h = _make_handlers(loop)
        result = h.knowledge(query="test")
        assert result == {"error": "Memory not available"}


# ── Spotify ────────────────────────────────────────────────────────


class TestSpotifyCommand:
    @pytest.fixture
    def spotify_handlers(self, loop):
        mock_session = MagicMock()
        mock_session.run = MagicMock(return_value="Now playing: jazz")
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


# ── Core tools ─────────────────────────────────────────────────────


class TestCoreTools:
    def test_listen(self, handlers):
        result = handlers.listen()
        assert result["status"] == "listening"
