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


@pytest.mark.asyncio
async def test_ingest_with_file_path(backend):
    """ingest() works with file paths too."""
    backend._ready = True

    with patch("cognee.add", new_callable=AsyncMock) as mock_add, patch("cognee.cognify", new_callable=AsyncMock):
        await backend.ingest("/path/to/doc.md", dataset="docs")

    mock_add.assert_awaited_once_with("/path/to/doc.md", dataset_name="docs")


@pytest.mark.asyncio
async def test_ingest_default_dataset(backend):
    """ingest() uses 'knowledge' as default dataset."""
    backend._ready = True

    with patch("cognee.add", new_callable=AsyncMock) as mock_add, patch("cognee.cognify", new_callable=AsyncMock):
        result = await backend.ingest("text")

    assert result["dataset"] == "knowledge"
    mock_add.assert_awaited_once_with("text", dataset_name="knowledge")


@pytest.mark.asyncio
async def test_ingest_tags_default_to_empty(backend):
    """ingest() defaults tags to empty list."""
    backend._ready = True

    with patch("cognee.add", new_callable=AsyncMock), patch("cognee.cognify", new_callable=AsyncMock):
        result = await backend.ingest("text")

    assert result["tags"] == []


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


@pytest.mark.asyncio
async def test_search_with_datasets_filter(backend):
    """search() passes datasets filter to cognee."""
    backend._ready = True

    with patch("cognee.search", new_callable=AsyncMock, return_value=[]) as mock_search:
        await backend.search("q", datasets=["ds1", "ds2"])

    call_kwargs = mock_search.call_args[1]
    assert call_kwargs["datasets"] == ["ds1", "ds2"]


@pytest.mark.asyncio
async def test_search_maps_search_types(backend):
    """search() correctly maps string search types to SearchType enum."""
    from cognee.api.v1.search import SearchType

    backend._ready = True

    for type_str, expected_enum in [
        ("graph_completion", SearchType.GRAPH_COMPLETION),
        ("chunks", SearchType.CHUNKS),
        ("summaries", SearchType.SUMMARIES),
    ]:
        with patch("cognee.search", new_callable=AsyncMock, return_value=[]):
            await backend.search("q", search_type=type_str)


@pytest.mark.asyncio
async def test_search_unknown_type_defaults_to_graph_completion(backend):
    """Unknown search_type falls back to GRAPH_COMPLETION."""
    backend._ready = True

    with patch("cognee.search", new_callable=AsyncMock, return_value=[]) as mock_search:
        await backend.search("q", search_type="nonexistent")

    from cognee.api.v1.search import SearchType

    call_kwargs = mock_search.call_args[1]
    assert call_kwargs["query_type"] == SearchType.GRAPH_COMPLETION


# -- Graph query tests ------------------------------------------------------


@pytest.mark.asyncio
async def test_list_entities_returns_all(backend):
    """list_entities() returns all nodes when no filters given."""
    backend._ready = True

    mock_engine = AsyncMock()
    mock_engine.get_graph_data = AsyncMock(
        return_value=(
            [
                ("id1", {"name": "Alice", "type": "Person"}),
                ("id2", {"name": "MIT", "type": "Organization"}),
            ],
            [],  # edges
        )
    )

    with patch(
        "cognee.infrastructure.databases.graph.get_graph_engine",
        new_callable=AsyncMock,
        return_value=mock_engine,
    ):
        results = await backend.list_entities()

    assert len(results) == 2
    assert results[0]["name"] == "Alice"
    assert results[1]["name"] == "MIT"


@pytest.mark.asyncio
async def test_list_entities_filters_by_type(backend):
    """list_entities(type_name=...) filters nodes by type."""
    backend._ready = True

    mock_engine = AsyncMock()
    mock_engine.get_graph_data = AsyncMock(
        return_value=(
            [
                ("id1", {"name": "Alice", "type": "Person"}),
                ("id2", {"name": "MIT", "type": "Organization"}),
            ],
            [],
        )
    )

    with patch(
        "cognee.infrastructure.databases.graph.get_graph_engine",
        new_callable=AsyncMock,
        return_value=mock_engine,
    ):
        results = await backend.list_entities(type_name="Person")

    assert len(results) == 1
    assert results[0]["name"] == "Alice"


@pytest.mark.asyncio
async def test_list_entities_filters_by_name(backend):
    """list_entities(name=...) does case-insensitive substring match."""
    backend._ready = True

    mock_engine = AsyncMock()
    mock_engine.get_graph_data = AsyncMock(
        return_value=(
            [
                ("id1", {"name": "Alice Smith", "type": "Person"}),
                ("id2", {"name": "Bob Jones", "type": "Person"}),
            ],
            [],
        )
    )

    with patch(
        "cognee.infrastructure.databases.graph.get_graph_engine",
        new_callable=AsyncMock,
        return_value=mock_engine,
    ):
        results = await backend.list_entities(name="alice")

    assert len(results) == 1
    assert results[0]["name"] == "Alice Smith"


@pytest.mark.asyncio
async def test_list_facts_returns_all_edges(backend):
    """list_facts() returns all edges when no filters given."""
    backend._ready = True

    mock_engine = AsyncMock()
    mock_engine.get_graph_data = AsyncMock(
        return_value=(
            [],
            [
                ("id1", "id2", "WORKS_AT", {"since": "2020"}),
                ("id2", "id3", "PART_OF", {}),
            ],
        )
    )

    with patch(
        "cognee.infrastructure.databases.graph.get_graph_engine",
        new_callable=AsyncMock,
        return_value=mock_engine,
    ):
        results = await backend.list_facts()

    assert len(results) == 2
    assert results[0]["relationship"] == "WORKS_AT"
    assert results[0]["properties"] == {"since": "2020"}


@pytest.mark.asyncio
async def test_list_facts_filters_by_entity_id(backend):
    """list_facts(entity_id=...) uses get_edges for that node."""
    backend._ready = True

    mock_engine = AsyncMock()
    mock_engine.get_edges = AsyncMock(
        return_value=[
            ("id1", "id2", "KNOWS", {"weight": 0.9}),
        ]
    )

    with patch(
        "cognee.infrastructure.databases.graph.get_graph_engine",
        new_callable=AsyncMock,
        return_value=mock_engine,
    ):
        results = await backend.list_facts(entity_id="id1")

    assert len(results) == 1
    mock_engine.get_edges.assert_awaited_once_with("id1")


@pytest.mark.asyncio
async def test_list_facts_filters_by_relationship_type(backend):
    """list_facts(relationship_type=...) filters edges by name."""
    backend._ready = True

    mock_engine = AsyncMock()
    mock_engine.get_graph_data = AsyncMock(
        return_value=(
            [],
            [
                ("id1", "id2", "WORKS_AT", {}),
                ("id2", "id3", "PART_OF", {}),
            ],
        )
    )

    with patch(
        "cognee.infrastructure.databases.graph.get_graph_engine",
        new_callable=AsyncMock,
        return_value=mock_engine,
    ):
        results = await backend.list_facts(relationship_type="WORKS_AT")

    assert len(results) == 1
    assert results[0]["relationship"] == "WORKS_AT"


# -- Graph mutation tests ---------------------------------------------------


@pytest.mark.asyncio
async def test_delete_calls_engine(backend):
    """delete() removes a node from the graph."""
    backend._ready = True

    mock_engine = AsyncMock()
    mock_engine.delete_node = AsyncMock()

    with patch(
        "cognee.infrastructure.databases.graph.get_graph_engine",
        new_callable=AsyncMock,
        return_value=mock_engine,
    ):
        result = await backend.delete("node-123")

    assert result["status"] == "ok"
    assert result["deleted_id"] == "node-123"
    mock_engine.delete_node.assert_awaited_once_with("node-123")


@pytest.mark.asyncio
async def test_update_entity_modifies_node(backend):
    """update_entity() merges new fields into existing node properties."""
    backend._ready = True

    mock_engine = AsyncMock()
    mock_engine.get_node = AsyncMock(return_value={"name": "Alice", "type": "Person"})
    mock_engine.delete_node = AsyncMock()
    mock_engine.add_node = AsyncMock()

    with patch(
        "cognee.infrastructure.databases.graph.get_graph_engine",
        new_callable=AsyncMock,
        return_value=mock_engine,
    ):
        result = await backend.update_entity("id1", {"name": "Alice Smith"})

    assert result["status"] == "ok"
    assert result["updated_fields"] == ["name"]
    mock_engine.delete_node.assert_awaited_once_with("id1")
    # Verify the re-added node has merged properties
    add_call = mock_engine.add_node.call_args
    assert add_call[0][0] == "id1"
    assert add_call[1]["properties"]["name"] == "Alice Smith"
    assert add_call[1]["properties"]["type"] == "Person"


@pytest.mark.asyncio
async def test_update_entity_not_found(backend):
    """update_entity() returns error if node doesn't exist."""
    backend._ready = True

    mock_engine = AsyncMock()
    mock_engine.get_node = AsyncMock(return_value=None)

    with patch(
        "cognee.infrastructure.databases.graph.get_graph_engine",
        new_callable=AsyncMock,
        return_value=mock_engine,
    ):
        result = await backend.update_entity("missing", {"name": "X"})

    assert result["status"] == "error"
    assert "not found" in result["reason"]


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


# -- Community building test ------------------------------------------------


@pytest.mark.asyncio
async def test_build_communities_calls_memify(backend):
    """build_communities() triggers cognee.memify()."""
    backend._ready = True

    with patch("cognee.memify", new_callable=AsyncMock) as mock_memify:
        result = await backend.build_communities()

    assert result["status"] == "ok"
    mock_memify.assert_awaited_once()
