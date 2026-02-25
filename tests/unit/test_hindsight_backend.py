"""Tests for HindsightBackend — thin wrapper around Hindsight MemoryEngine."""

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
