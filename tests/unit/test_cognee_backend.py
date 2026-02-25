"""Tests for CogneeBackend — wrapper around cognee's pip API."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from clarvis.agent.memory.cognee_backend import CogneeBackend

# -- Fixtures ---------------------------------------------------------------


@pytest.fixture()
def backend():
    """Create a CogneeBackend with test defaults."""
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


# -- Lifecycle tests --------------------------------------------------------


@pytest.mark.asyncio
async def test_not_ready_before_start(backend):
    assert backend.ready is False


@pytest.mark.asyncio
async def test_start_configures_cognee(backend):
    """start() should configure all cognee backends and set ready=True."""
    import cognee

    with (
        patch.object(cognee.config, "set_relational_db_config") as mock_rel,
        patch.object(cognee.config, "set_vector_db_config") as mock_vec,
        patch.object(cognee.config, "set_graph_db_config") as mock_graph,
        patch.object(cognee.config, "set_llm_config") as mock_llm,
    ):
        await backend.start()

    assert backend.ready is True

    # Verify relational config
    rel_call = mock_rel.call_args[0][0]
    assert rel_call["db_provider"] == "postgres"
    assert rel_call["db_host"] == "localhost"
    assert rel_call["db_name"] == "test_knowledge"

    # Verify vector config
    vec_call = mock_vec.call_args[0][0]
    assert vec_call["vector_db_provider"] == "pgvector"
    assert "postgresql://" in vec_call["vector_db_url"]

    # Verify graph config
    graph_call = mock_graph.call_args[0][0]
    assert graph_call["graph_database_provider"] == "kuzu"
    assert graph_call["graph_file_path"] == "/tmp/test_graph_kuzu"

    # Verify LLM config
    llm_call = mock_llm.call_args[0][0]
    assert llm_call["llm_provider"] == "anthropic"
    assert llm_call["llm_model"] == "claude-sonnet-4-6"
    assert llm_call["llm_api_key"] == "test-key"


@pytest.mark.asyncio
async def test_stop_clears_ready(backend):
    backend._ready = True
    await backend.stop()
    assert backend.ready is False


# -- Ingest tests -----------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_calls_add_and_cognify(backend):
    """ingest() should call cognee.add then cognee.cognify."""
    backend._ready = True

    with (
        patch("cognee.add", new_callable=AsyncMock) as mock_add,
        patch("cognee.cognify", new_callable=AsyncMock) as mock_cognify,
    ):
        result = await backend.ingest("some text", dataset="test_ds", tags=["tag1"])

    assert result["status"] == "ok"
    assert result["dataset"] == "test_ds"
    assert result["tags"] == ["tag1"]

    mock_add.assert_awaited_once_with("some text", dataset_name="test_ds")
    from clarvis.agent.memory.entity_types import ENTITY_TYPES

    mock_cognify.assert_awaited_once_with(
        datasets=["test_ds"],
        graph_model=list(ENTITY_TYPES.values()),
    )


# -- Search tests -----------------------------------------------------------


@pytest.mark.asyncio
async def test_search_delegates_to_cognee(backend):
    """search() should call cognee.search with correct params."""
    backend._ready = True

    mock_result = MagicMock()
    mock_result.search_result = {"name": "Test Entity"}
    mock_result.dataset_id = None
    mock_result.dataset_name = "test_ds"

    with patch("cognee.search", new_callable=AsyncMock, return_value=[mock_result]) as mock_search:
        results = await backend.search("test query", search_type="graph_completion")

    assert len(results) == 1
    assert results[0]["result"] == {"name": "Test Entity"}
    assert results[0]["dataset_name"] == "test_ds"

    call_kwargs = mock_search.call_args[1]
    assert call_kwargs["query_text"] == "test query"
    assert call_kwargs["top_k"] == 10


# -- Graph mutation tests ---------------------------------------------------


@pytest.mark.asyncio
async def test_merge_entities(backend):
    """merge_entities() re-points edges to survivor and deletes duplicates."""
    backend._ready = True

    mock_engine = AsyncMock()
    mock_engine.get_edges = AsyncMock(
        return_value=[
            ("id2", "id3", "KNOWS", {}),
        ]
    )
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
    assert result["merged_count"] == 1
    # Edge from id2->id3 should become id1->id3
    mock_engine.add_edge.assert_awaited_once_with("id1", "id3", "KNOWS", {})
    mock_engine.delete_node.assert_awaited_once_with("id2")


@pytest.mark.asyncio
async def test_merge_entities_needs_at_least_two(backend):
    """merge_entities() requires at least 2 IDs."""
    backend._ready = True
    result = await backend.merge_entities(["id1"])
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_merge_entities_skips_self_loops(backend):
    """merge_entities() skips edges that would create self-loops."""
    backend._ready = True

    mock_engine = AsyncMock()
    # Edge from dup to survivor would become a self-loop
    mock_engine.get_edges = AsyncMock(
        return_value=[
            ("id2", "id1", "RELATED", {}),
        ]
    )
    mock_engine.add_edge = AsyncMock()
    mock_engine.delete_node = AsyncMock()

    with patch(
        "cognee.infrastructure.databases.graph.get_graph_engine",
        new_callable=AsyncMock,
        return_value=mock_engine,
    ):
        result = await backend.merge_entities(["id1", "id2"])

    assert result["status"] == "ok"
    # Self-loop should have been skipped
    mock_engine.add_edge.assert_not_awaited()
