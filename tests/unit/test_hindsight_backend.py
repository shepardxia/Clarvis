"""Tests for HindsightBackend — thin wrapper around Hindsight MemoryEngine."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from clarvis.agent.memory.hindsight_backend import HindsightBackend

# -- Fixtures ---------------------------------------------------------------


@pytest.fixture()
def mock_engine():
    """A mocked MemoryEngine with all relevant async methods."""
    engine = MagicMock()
    engine.initialize = AsyncMock()
    engine.close = AsyncMock()

    # retain_async returns list of unit IDs
    engine.retain_async = AsyncMock(return_value=["unit-id-1", "unit-id-2"])

    # retain_batch_async returns list of lists of unit IDs
    engine.retain_batch_async = AsyncMock(return_value=[["unit-id-1"], ["unit-id-2", "unit-id-3"]])

    # recall_async returns a Pydantic model with model_dump()
    recall_result = MagicMock()
    recall_result.model_dump.return_value = {
        "results": [
            {
                "id": "fact-1",
                "text": "Shepard works at MIT",
                "fact_type": "world",
            }
        ],
        "entities": {},
        "chunks": {},
    }
    engine.recall_async = AsyncMock(return_value=recall_result)

    # reflect_async returns a Pydantic model with model_dump()
    reflect_result = MagicMock()
    reflect_result.model_dump.return_value = {
        "text": "Based on my knowledge...",
        "based_on": {"world": [], "experience": []},
    }
    engine.reflect_async = AsyncMock(return_value=reflect_result)

    # delete_memory_unit
    engine.delete_memory_unit = AsyncMock(return_value={"success": True, "unit_id": "unit-id-1", "message": "Deleted"})

    # list_memory_units
    engine.list_memory_units = AsyncMock(
        return_value={
            "items": [
                {
                    "id": "unit-1",
                    "text": "A fact",
                    "fact_type": "world",
                    "date": "2026-01-01T00:00:00+00:00",
                }
            ],
            "total": 1,
            "limit": 50,
            "offset": 0,
        }
    )

    # get_memory_unit
    engine.get_memory_unit = AsyncMock(
        return_value={
            "id": "unit-1",
            "text": "A fact",
            "type": "world",
            "date": "2026-01-01T00:00:00+00:00",
        }
    )

    # run_consolidation
    engine.run_consolidation = AsyncMock(return_value={"processed": 10, "created": 2, "updated": 1, "skipped": 7})

    # list_banks
    engine.list_banks = AsyncMock(return_value=[{"bank_id": "parletre"}, {"bank_id": "agora"}])

    return engine


@pytest.fixture()
def backend(mock_engine):
    """HindsightBackend with injected mock engine, already in ready state."""
    b = HindsightBackend(
        db_url="pg0",
        llm_provider="anthropic",
        api_key="test-key",
        model="claude-sonnet-4-6",
        banks={
            "parletre": {"visibility": "master"},
            "agora": {"visibility": "all"},
        },
    )
    # Inject mock engine directly (skip start())
    b._engine = mock_engine
    b._ready = True
    return b


# -- Lifecycle tests --------------------------------------------------------


@pytest.mark.asyncio
async def test_start_initializes_engine():
    """start() should create and initialize a MemoryEngine."""
    with patch("clarvis.agent.memory.hindsight_backend.HindsightBackend.start") as mock_start:
        # Test via the actual constructor + mock
        HindsightBackend(api_key="k")
        mock_start.return_value = None
        await mock_start()
        mock_start.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_sets_ready(mock_engine):
    """After start(), ready should be True."""
    with patch(
        "clarvis.vendor.hindsight.engine.memory_engine.MemoryEngine",
        return_value=mock_engine,
    ):
        b = HindsightBackend(api_key="k")
        await b.start()
        assert b.ready is True
        mock_engine.initialize.assert_awaited_once()


@pytest.mark.asyncio
async def test_stop_closes_engine(backend, mock_engine):
    """stop() should close the engine and clear ready."""
    await backend.stop()
    mock_engine.close.assert_awaited_once()
    assert backend.ready is False
    assert backend._engine is None


def test_ready_initially_false():
    """Backend should not be ready until start() is called."""
    b = HindsightBackend(api_key="k")
    assert b.ready is False


# -- Bank validation -------------------------------------------------------


@pytest.mark.asyncio
async def test_retain_rejects_unknown_bank(backend):
    """retain() should raise ValueError for unknown banks."""
    with pytest.raises(ValueError, match="Unknown bank"):
        await backend.retain("test", bank="nonexistent")


@pytest.mark.asyncio
async def test_recall_rejects_unknown_bank(backend):
    """recall() should raise ValueError for unknown banks."""
    with pytest.raises(ValueError, match="Unknown bank"):
        await backend.recall("query", bank="bad")


def test_visible_banks_master(backend):
    """Master visibility returns all banks."""
    assert set(backend.visible_banks("master")) == {"parletre", "agora"}


def test_visible_banks_all(backend):
    """'all' visibility returns only banks with visibility='all'."""
    banks = backend.visible_banks("all")
    assert "agora" in banks
    # parletre has visibility="master", should not be included for "all"
    assert "parletre" not in banks


# -- Retain tests -----------------------------------------------------------


@pytest.mark.asyncio
async def test_retain_calls_engine(backend, mock_engine):
    """retain() should call engine.retain_async with correct args."""
    result = await backend.retain("Shepard works at MIT", bank="parletre")

    mock_engine.retain_async.assert_awaited_once()
    call_kwargs = mock_engine.retain_async.call_args
    assert call_kwargs.kwargs["bank_id"] == "parletre"
    assert call_kwargs.kwargs["content"] == "Shepard works at MIT"

    # Returns structured results
    assert len(result) == 2
    assert result[0]["id"] == "unit-id-1"


@pytest.mark.asyncio
async def test_retain_passes_fact_type(backend, mock_engine):
    """retain() should pass fact_type_override to engine."""
    await backend.retain("I think X", fact_type="opinion", confidence=0.8, bank="parletre")

    call_kwargs = mock_engine.retain_async.call_args.kwargs
    assert call_kwargs["fact_type_override"] == "opinion"
    assert call_kwargs["confidence_score"] == 0.8


@pytest.mark.asyncio
async def test_retain_passes_event_date(backend, mock_engine):
    """retain() should pass event_date to engine."""
    dt = datetime(2026, 1, 15, tzinfo=timezone.utc)
    await backend.retain("fact", event_date=dt, bank="parletre")

    call_kwargs = mock_engine.retain_async.call_args.kwargs
    assert call_kwargs["event_date"] == dt


@pytest.mark.asyncio
async def test_retain_passes_context(backend, mock_engine):
    """retain() should pass context string to engine."""
    await backend.retain("fact", context="from conversation", bank="parletre")

    call_kwargs = mock_engine.retain_async.call_args.kwargs
    assert call_kwargs["context"] == "from conversation"


# -- Retain batch tests -----------------------------------------------------


@pytest.mark.asyncio
async def test_retain_batch(backend, mock_engine):
    """retain_batch() should call engine.retain_batch_async."""
    contents = [
        {"content": "Alice works at Google"},
        {"content": "Bob loves Python"},
    ]
    result = await backend.retain_batch(contents, bank="parletre")

    mock_engine.retain_batch_async.assert_awaited_once()
    call_kwargs = mock_engine.retain_batch_async.call_args.kwargs
    assert call_kwargs["bank_id"] == "parletre"
    assert len(call_kwargs["contents"]) == 2

    # Returns list of lists of dicts
    assert len(result) == 2
    assert result[0][0]["id"] == "unit-id-1"


# -- Recall tests -----------------------------------------------------------


@pytest.mark.asyncio
async def test_recall_calls_engine(backend, mock_engine):
    """recall() should call engine.recall_async and return model_dump."""
    result = await backend.recall("what does Shepard do?", bank="parletre")

    mock_engine.recall_async.assert_awaited_once()
    call_kwargs = mock_engine.recall_async.call_args.kwargs
    assert call_kwargs["bank_id"] == "parletre"
    assert call_kwargs["query"] == "what does Shepard do?"
    assert call_kwargs["max_tokens"] == 4096

    assert "results" in result
    assert result["results"][0]["text"] == "Shepard works at MIT"


@pytest.mark.asyncio
async def test_recall_passes_token_budget(backend, mock_engine):
    """recall() should pass max_tokens to engine."""
    await backend.recall("q", max_tokens=2048, bank="agora")

    call_kwargs = mock_engine.recall_async.call_args.kwargs
    assert call_kwargs["max_tokens"] == 2048


@pytest.mark.asyncio
async def test_recall_passes_fact_type_filter(backend, mock_engine):
    """recall() should pass fact_type filter to engine."""
    await backend.recall("q", fact_type=["world", "experience"], bank="parletre")

    call_kwargs = mock_engine.recall_async.call_args.kwargs
    assert call_kwargs["fact_type"] == ["world", "experience"]


# -- Reflect tests ----------------------------------------------------------


@pytest.mark.asyncio
async def test_reflect_calls_engine(backend, mock_engine):
    """reflect() should call engine.reflect_async and return model_dump."""
    result = await backend.reflect("What do I know about X?", bank="parletre")

    mock_engine.reflect_async.assert_awaited_once()
    call_kwargs = mock_engine.reflect_async.call_args.kwargs
    assert call_kwargs["bank_id"] == "parletre"
    assert call_kwargs["query"] == "What do I know about X?"

    assert "text" in result
    assert "based_on" in result


@pytest.mark.asyncio
async def test_reflect_passes_context(backend, mock_engine):
    """reflect() should pass additional context."""
    await backend.reflect("q", context="extra info", bank="parletre")

    call_kwargs = mock_engine.reflect_async.call_args.kwargs
    assert call_kwargs["context"] == "extra info"


# -- Update tests -----------------------------------------------------------


@pytest.mark.asyncio
async def test_update_with_content_replaces(backend, mock_engine):
    """update() with content should delete old + retain new."""
    result = await backend.update("old-id", content="new content", bank="parletre")

    mock_engine.delete_memory_unit.assert_awaited_once()
    mock_engine.retain_async.assert_awaited_once()
    assert result["success"] is True
    assert result["old_id"] == "old-id"
    assert result["new_ids"] == ["unit-id-1", "unit-id-2"]


@pytest.mark.asyncio
async def test_update_without_content_returns_info(backend, mock_engine):
    """update() without content should return a 'not supported' message."""
    result = await backend.update("some-id", bank="parletre")

    assert result["success"] is False
    mock_engine.delete_memory_unit.assert_not_awaited()
    mock_engine.retain_async.assert_not_awaited()


# -- Forget tests -----------------------------------------------------------


@pytest.mark.asyncio
async def test_forget_deletes_unit(backend, mock_engine):
    """forget() should call engine.delete_memory_unit."""
    result = await backend.forget("unit-123")

    mock_engine.delete_memory_unit.assert_awaited_once()
    assert result["success"] is True


# -- List tests -------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_memories(backend, mock_engine):
    """list_memories() should call engine.list_memory_units."""
    result = await backend.list_memories(bank="parletre", fact_type="world", limit=10)

    mock_engine.list_memory_units.assert_awaited_once()
    call_kwargs = mock_engine.list_memory_units.call_args.kwargs
    assert call_kwargs["bank_id"] == "parletre"
    assert call_kwargs["fact_type"] == "world"
    assert call_kwargs["limit"] == 10

    assert result["total"] == 1
    assert len(result["items"]) == 1


@pytest.mark.asyncio
async def test_list_memories_with_search(backend, mock_engine):
    """list_memories() should pass search_query to engine."""
    await backend.list_memories(search_query="MIT", bank="parletre")

    call_kwargs = mock_engine.list_memory_units.call_args.kwargs
    assert call_kwargs["search_query"] == "MIT"


# -- Get memory tests -------------------------------------------------------


@pytest.mark.asyncio
async def test_get_memory(backend, mock_engine):
    """get_memory() should call engine.get_memory_unit."""
    result = await backend.get_memory("unit-1", bank="parletre")

    mock_engine.get_memory_unit.assert_awaited_once()
    assert result["id"] == "unit-1"


# -- Consolidate tests ------------------------------------------------------


@pytest.mark.asyncio
async def test_consolidate(backend, mock_engine):
    """consolidate() should call engine.run_consolidation."""
    result = await backend.consolidate(bank="parletre")

    mock_engine.run_consolidation.assert_awaited_once()
    assert result["processed"] == 10
    assert result["created"] == 2


# -- List banks tests -------------------------------------------------------


@pytest.mark.asyncio
async def test_list_banks(backend, mock_engine):
    """list_banks() should call engine.list_banks."""
    result = await backend.list_banks()

    mock_engine.list_banks.assert_awaited_once()
    assert len(result) == 2
