"""CogneeBackend — configuration, search, merge with self-loop prevention."""

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
async def test_cognee_configuration_and_search(backend):
    """start() configures cognee backends → search() maps results correctly."""
    import cognee

    # configuration phase
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

    # search phase — result mapping
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
async def test_cognee_entity_merge(backend):
    """Merge re-points edges to survivor, self-loops are skipped."""
    backend._ready = True

    # normal merge: edges re-pointed to survivor
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

    # self-loop prevention: edge pointing back to survivor is skipped
    mock_engine2 = AsyncMock()
    mock_engine2.get_edges = AsyncMock(return_value=[("id2", "id1", "RELATED", {})])
    mock_engine2.add_edge = AsyncMock()
    mock_engine2.delete_node = AsyncMock()

    with patch(
        "cognee.infrastructure.databases.graph.get_graph_engine",
        new_callable=AsyncMock,
        return_value=mock_engine2,
    ):
        result2 = await backend.merge_entities(["id1", "id2"])

    assert result2["status"] == "ok"
    mock_engine2.add_edge.assert_not_awaited()
