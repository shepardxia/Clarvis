"""MemoryStore KG methods — configuration, search, merge with self-loop prevention."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("cognee", reason="cognee not installed (memory extra required)")

from clarvis.memory.store import MemoryStore

# -- Fixtures ---------------------------------------------------------------


@pytest.fixture()
def store():
    return MemoryStore(
        kg_db_host="localhost",
        kg_db_port=5432,
        kg_db_name="test_knowledge",
        kg_db_username="testuser",
        kg_db_password="",
        kg_graph_path="/tmp/test_graph_kuzu",
        kg_llm_provider="anthropic",
        kg_llm_model="claude-sonnet-4-6",
        kg_llm_api_key="test-key",
    )


# -- Tests ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cognee_configuration_and_search(store):
    """start() configures cognee backends → kg_search() maps results correctly."""
    import cognee

    # configuration phase — patch hindsight to avoid real DB, cognee to avoid real config
    with (
        patch("hindsight_api.engine.memory_engine.MemoryEngine", side_effect=RuntimeError("no db")),
        patch.object(cognee.config, "set_relational_db_config") as mock_rel,
        patch.object(cognee.config, "set_vector_db_config") as mock_vec,
        patch.object(cognee.config, "set_graph_db_config") as mock_graph,
        patch.object(cognee.config, "set_llm_config") as mock_llm,
    ):
        await store.start()

    assert store.kg_ready is True
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
        results = await store.kg_search("test query", search_type="graph_completion")

    assert len(results) == 1
    assert results[0]["result"] == {"name": "Test Entity"}
    assert results[0]["dataset_name"] == "test_ds"


@pytest.mark.asyncio
async def test_cognee_entity_merge(store):
    """Merge re-points edges to survivor, self-loops are skipped."""
    store._kg_ready = True

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
        result = await store.kg_merge_entities(["id1", "id2"])

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
        result2 = await store.kg_merge_entities(["id1", "id2"])

    assert result2["status"] == "ok"
    mock_engine2.add_edge.assert_not_awaited()
