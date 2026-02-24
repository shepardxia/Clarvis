"""Tests for DualMemoryService — unified orchestration of memU + Graphiti."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from clarvis.services.memory.service import DualMemoryService
from clarvis.widget.config import DatasetConfig

# -- Fixtures ---------------------------------------------------------------


@pytest.fixture()
def dataset_configs():
    return {
        "parletre": DatasetConfig(visibility="master"),
        "agora": DatasetConfig(visibility="all"),
    }


@pytest.fixture()
def service(tmp_path: Path, dataset_configs):
    """Create a DualMemoryService with mocked backends."""
    svc = DualMemoryService(
        data_dir=tmp_path / "memory",
        dataset_configs=dataset_configs,
        api_key="test-key",
    )
    # Replace backends with mocks
    svc._memu = MagicMock()
    svc._memu.ready = True
    svc._memu.start = AsyncMock()
    svc._memu.search = AsyncMock(return_value=[{"text": "memu result"}])
    svc._memu.add = AsyncMock(return_value={"status": "ok"})
    svc._memu.forget = AsyncMock(return_value={"status": "ok", "deleted": "123"})
    svc._memu.visible_datasets = MagicMock(return_value=["parletre", "agora"])
    svc._memu.get_categories = AsyncMock(
        return_value=[
            {"category": "parletre", "item_count": 3},
            {"category": "agora", "item_count": 5},
        ]
    )
    svc._memu.memorize = AsyncMock(return_value={"status": "ok"})
    svc._memu.recall = AsyncMock(
        return_value={
            "categories": [{"name": "personal", "summary": "user info"}],
            "items": [{"summary": "likes coffee", "memory_type": "profile"}],
            "resources": [],
            "next_step_query": "What else?",
        }
    )

    svc._graphiti = MagicMock()
    svc._graphiti.ready = True
    svc._graphiti.start = AsyncMock()
    svc._graphiti.close = AsyncMock()
    svc._graphiti.search = AsyncMock(return_value=[{"fact": "graphiti fact"}])
    svc._graphiti.add_episode = AsyncMock()
    svc._graphiti.group_ids_for = MagicMock(return_value=["parletre", "agora"])

    return svc


# -- Lifecycle tests --------------------------------------------------------


@pytest.mark.asyncio
async def test_start_calls_both_backends(service):
    """start() should initialize both backends and set ready."""
    await service.start()
    service._memu.start.assert_awaited_once()
    service._graphiti.start.assert_awaited_once()
    assert service.ready is True


@pytest.mark.asyncio
async def test_stop_closes_graphiti(service):
    """stop() should close Graphiti and clear ready flag."""
    service._ready = True
    await service.stop()
    service._graphiti.close.assert_awaited_once()
    assert service.ready is False


def test_ready_initially_false(tmp_path, dataset_configs):
    """Service should not be ready until start() is called."""
    svc = DualMemoryService(data_dir=tmp_path, dataset_configs=dataset_configs, api_key="k")
    assert svc.ready is False


# -- Search tests -----------------------------------------------------------


@pytest.mark.asyncio
async def test_search_merges_both_backends(service):
    """search() should combine results from memU and Graphiti."""
    results = await service.search("test query")
    assert len(results) == 2
    assert results[0] == {"text": "memu result"}
    assert results[1] == {"fact": "graphiti fact"}
    service._memu.search.assert_awaited_once()
    service._graphiti.search.assert_awaited_once()


@pytest.mark.asyncio
async def test_search_skips_unready_backend(service):
    """search() should skip backends that aren't ready."""
    service._graphiti.ready = False
    results = await service.search("test")
    assert len(results) == 1
    assert results[0] == {"text": "memu result"}
    service._graphiti.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_passes_visibility(service):
    """search() should pass visibility to both backends for scoping."""
    await service.search("q", visibility="all")
    service._memu.visible_datasets.assert_called_with(visibility="all")
    service._graphiti.group_ids_for.assert_called_with(visibility="all")


# -- Add tests --------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_writes_to_both(service):
    """add() should write to both backends."""
    result = await service.add("fact", dataset="agora")
    assert result["status"] == "ok"
    assert result["dataset"] == "agora"
    service._memu.add.assert_awaited_once()
    service._graphiti.add_episode.assert_awaited_once()


@pytest.mark.asyncio
async def test_add_skips_unready_graphiti(service):
    """add() should succeed with just memU if Graphiti is down."""
    service._graphiti.ready = False
    result = await service.add("fact", dataset="parletre")
    assert result["status"] == "ok"
    assert "graphiti" not in result["backends"]


# -- Forget tests -----------------------------------------------------------


@pytest.mark.asyncio
async def test_forget_delegates_to_memu(service):
    """forget() should delegate to memU."""
    result = await service.forget("item-123", dataset="agora")
    assert result["status"] == "ok"
    service._memu.forget.assert_awaited_once_with("item-123", dataset="agora")


@pytest.mark.asyncio
async def test_forget_returns_error_when_memu_down(service):
    """forget() should return error when memU is not ready."""
    service._memu.ready = False
    result = await service.forget("item-123", dataset="agora")
    assert "error" in result


# -- Recall tests -----------------------------------------------------------


@pytest.mark.asyncio
async def test_recall_returns_structured_result(service):
    """recall() should return structured dict with both backends' data."""
    result = await service.recall("what do I like?")
    assert "categories" in result
    assert "items" in result
    assert "graphiti_facts" in result
    assert result["graphiti_facts"] == [{"fact": "graphiti fact"}]
    service._memu.recall.assert_awaited_once()
    service._graphiti.search.assert_awaited_once()


@pytest.mark.asyncio
async def test_recall_passes_context_messages(service):
    """recall() should pass context_messages to memU backend."""
    msgs = [{"role": "user", "content": "hello"}]
    await service.recall("q", context_messages=msgs)
    call_kwargs = service._memu.recall.call_args[1]
    assert call_kwargs["context_messages"] == msgs


@pytest.mark.asyncio
async def test_recall_graceful_graphiti_failure(service):
    """recall() should continue with memU results if Graphiti fails."""
    service._graphiti.search = AsyncMock(side_effect=RuntimeError("boom"))
    result = await service.recall("q")
    assert "categories" in result
    assert result["graphiti_facts"] == []


@pytest.mark.asyncio
async def test_recall_empty_when_memu_not_ready(service):
    """recall() should return empty structure when memU is not ready."""
    service._memu.ready = False
    result = await service.recall("q")
    # Should still have graphiti_facts
    assert "graphiti_facts" in result


# -- Ingest transcript ------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_transcript_feeds_memu(service):
    """ingest_transcript() should feed text to memU (Graphiti via pipeline step)."""
    result = await service.ingest_transcript("hello world", dataset="parletre")
    assert result["status"] == "ok"
    service._memu.memorize.assert_awaited_once()
    # Graphiti is no longer called directly — GraphitiStep in the pipeline handles it
    service._graphiti.add_episode.assert_not_awaited()
