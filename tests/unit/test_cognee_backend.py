"""CogneeBackend — configuration, ingest pipeline, search, merge with self-loop prevention."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("cognee", reason="cognee not installed (memory extra required)")

from clarvis.agent.memory.cognee_backend import CogneeBackend

# -- Fixtures ---------------------------------------------------------------


@pytest.fixture()
def backend():
    return CogneeBackend(
        db_host="localhost",
        db_port=5432,
        db_name="test_knowledge",
        db_username="testuser",
        db_password="",
        graph_path="/tmp/test_graph_kuzu",
        llm_provider="anthropic",
        llm_model="claude-sonnet-4-6",
        llm_api_key="test-key",
    )


# -- Tests ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_configures_cognee(backend):
    """start() configures all 4 cognee backends and sets ready=True."""
    import cognee

    with (
        patch.object(cognee.config, "set_relational_db_config") as mock_rel,
        patch.object(cognee.config, "set_vector_db_config") as mock_vec,
        patch.object(cognee.config, "set_graph_db_config") as mock_graph,
        patch.object(cognee.config, "set_llm_config") as mock_llm,
    ):
        await backend.start()

    assert backend.ready is True
    assert mock_rel.call_args[0][0]["db_provider"] == "postgres"
    assert mock_vec.call_args[0][0]["vector_db_provider"] == "pgvector"
    assert mock_graph.call_args[0][0]["graph_database_provider"] == "kuzu"
    assert mock_llm.call_args[0][0]["llm_provider"] == "anthropic"


@pytest.mark.asyncio
async def test_ingest_calls_add_and_cognify(backend):
    """ingest() calls cognee.add then cognee.cognify with entity types."""
    backend._ready = True

    with (
        patch("cognee.add", new_callable=AsyncMock) as mock_add,
        patch("cognee.cognify", new_callable=AsyncMock) as mock_cognify,
    ):
        result = await backend.ingest("some text", dataset="test_ds", tags=["tag1"])

    assert result["status"] == "ok"
    assert result["dataset"] == "test_ds"
    mock_add.assert_awaited_once_with("some text", dataset_name="test_ds")
    mock_cognify.assert_awaited_once()


@pytest.mark.asyncio
async def test_search_delegates_to_cognee(backend):
    """search() maps cognee results to dicts with correct fields."""
    backend._ready = True

    mock_result = MagicMock()
    mock_result.search_result = {"name": "Test Entity"}
    mock_result.dataset_id = None
    mock_result.dataset_name = "test_ds"

    with patch("cognee.search", new_callable=AsyncMock, return_value=[mock_result]):
        results = await backend.search("test query", search_type="graph_completion")

    assert len(results) == 1
    assert results[0]["result"] == {"name": "Test Entity"}
    assert results[0]["dataset_name"] == "test_ds"


@pytest.mark.asyncio
async def test_merge_entities(backend):
    """merge_entities() re-points edges to survivor and deletes duplicates."""
    backend._ready = True

    mock_engine = AsyncMock()
    mock_engine.get_edges = AsyncMock(return_value=[("id2", "id3", "KNOWS", {})])
    mock_engine.add_edge = AsyncMock()
    mock_engine.delete_node = AsyncMock()

    with patch(
        "cognee.infrastructure.databases.graph.get_graph_engine",
        new_callable=AsyncMock,
        return_value=mock_engine,
    ):
        result = await backend.merge_entities(["id1", "id2"])

    assert result["status"] == "ok"
    assert result["survivor_id"] == "id1"
    mock_engine.add_edge.assert_awaited_once_with("id1", "id3", "KNOWS", {})
    mock_engine.delete_node.assert_awaited_once_with("id2")


@pytest.mark.asyncio
async def test_merge_entities_skips_self_loops(backend):
    """Edges that would create self-loops are skipped."""
    backend._ready = True

    mock_engine = AsyncMock()
    mock_engine.get_edges = AsyncMock(return_value=[("id2", "id1", "RELATED", {})])
    mock_engine.add_edge = AsyncMock()
    mock_engine.delete_node = AsyncMock()

    with patch(
        "cognee.infrastructure.databases.graph.get_graph_engine",
        new_callable=AsyncMock,
        return_value=mock_engine,
    ):
        result = await backend.merge_entities(["id1", "id2"])

    assert result["status"] == "ok"
    mock_engine.add_edge.assert_not_awaited()
