"""Cognee knowledge graph backend.

Thin wrapper around cognee's pip API for document ingestion, knowledge graph
construction, and graph queries.  Configures cognee with PostgreSQL (relational
+ vector via pgvector) and kuzu (embedded graph) backends.
"""

import logging
import os
from pathlib import Path
from typing import Any

from cognee.api.v1.search import SearchType

from .entity_types import ENTITY_TYPES

logger = logging.getLogger(__name__)

# Map user-facing search type strings to cognee SearchType enum values.
_SEARCH_TYPE_MAP: dict[str, SearchType] = {
    "graph_completion": SearchType.GRAPH_COMPLETION,
    "chunks": SearchType.CHUNKS,
    "summaries": SearchType.SUMMARIES,
    "rag_completion": SearchType.RAG_COMPLETION,
    "graph_summary_completion": SearchType.GRAPH_SUMMARY_COMPLETION,
    "natural_language": SearchType.NATURAL_LANGUAGE,
    "triplet_completion": SearchType.TRIPLET_COMPLETION,
}


class CogneeBackend:
    """Wrapper around cognee pipeline for document knowledge graph operations.

    Manages lifecycle, configures backends, and exposes ingest/search/graph
    operations.  Uses kuzu (embedded) for the graph layer and PostgreSQL +
    pgvector for relational + vector storage.

    Parameters
    ----------
    db_host:
        PostgreSQL host (default ``"localhost"``).
    db_port:
        PostgreSQL port (default ``5432``).
    db_name:
        Database name for cognee's relational + vector data.
    db_username:
        PostgreSQL username (defaults to ``$USER``).
    db_password:
        PostgreSQL password (defaults to ``""``).
    graph_path:
        File-system path for kuzu's embedded graph database.
    llm_provider:
        LLM provider for entity extraction (default ``"anthropic"``).
    llm_model:
        LLM model name (default ``"claude-sonnet-4-6"``).
    llm_api_key:
        API key for the LLM provider.  Falls back to
        ``$ANTHROPIC_API_KEY``.
    """

    def __init__(
        self,
        *,
        db_host: str = "localhost",
        db_port: int = 5432,
        db_name: str = "clarvis_knowledge",
        db_username: str | None = None,
        db_password: str = "",
        graph_path: str | Path | None = None,
        llm_provider: str = "anthropic",
        llm_model: str = "claude-sonnet-4-6",
        llm_api_key: str | None = None,
    ) -> None:
        self._db_host = db_host
        self._db_port = db_port
        self._db_name = db_name
        self._db_username = db_username or os.environ.get("USER", "")
        self._db_password = db_password
        self._graph_path = str(
            Path(graph_path).expanduser()
            if graph_path
            else Path.home() / ".clarvis" / "memory" / "knowledge_graph_kuzu"
        )
        self._llm_provider = llm_provider
        self._llm_model = llm_model
        self._llm_api_key = llm_api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._ready = False

    # ── Lifecycle ───────────────────────────────────────────────

    async def start(self) -> None:
        """Configure cognee backends and mark as ready."""
        import cognee

        db_url = f"postgresql://{self._db_username}:{self._db_password}@{self._db_host}:{self._db_port}/{self._db_name}"

        cognee.config.set_relational_db_config(
            {
                "db_provider": "postgres",
                "db_host": self._db_host,
                "db_port": str(self._db_port),
                "db_name": self._db_name,
                "db_username": self._db_username,
                "db_password": self._db_password,
            }
        )
        cognee.config.set_vector_db_config(
            {
                "vector_db_provider": "pgvector",
                "vector_db_url": db_url,
            }
        )
        cognee.config.set_graph_db_config(
            {
                "graph_database_provider": "kuzu",
                "graph_file_path": self._graph_path,
                "graph_filename": Path(self._graph_path).name,
            }
        )
        cognee.config.set_llm_config(
            {
                "llm_provider": self._llm_provider,
                "llm_model": self._llm_model,
                "llm_api_key": self._llm_api_key,
            }
        )

        self._ready = True
        logger.info(
            "CogneeBackend started (graph=%s, db=%s/%s)",
            self._graph_path,
            self._db_host,
            self._db_name,
        )

    async def stop(self) -> None:
        """Mark backend as stopped."""
        self._ready = False
        logger.info("CogneeBackend stopped")

    @property
    def ready(self) -> bool:
        return self._ready

    # ── Ingest ──────────────────────────────────────────────────

    async def ingest(
        self,
        content_or_path: str,
        *,
        dataset: str = "knowledge",
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Ingest content or a file path through the cognee pipeline.

        Runs ``cognee.add()`` followed by ``cognee.cognify()`` with our custom
        entity types.  Returns a status report.

        Parameters
        ----------
        content_or_path:
            Raw text content or a file-system path to ingest.
        dataset:
            Cognee dataset name to store under.
        tags:
            Optional tags for organization (stored as metadata).
        """
        import cognee

        await cognee.add(content_or_path, dataset_name=dataset)
        await cognee.cognify(
            datasets=[dataset],
            graph_model=list(ENTITY_TYPES.values()),
        )

        return {
            "status": "ok",
            "dataset": dataset,
            "tags": tags or [],
        }

    # ── Search ──────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        *,
        search_type: str = "graph_completion",
        datasets: list[str] | None = None,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """Search the knowledge graph.

        Parameters
        ----------
        query:
            Natural language query.
        search_type:
            One of: ``graph_completion``, ``chunks``, ``summaries``,
            ``rag_completion``, ``graph_summary_completion``,
            ``natural_language``, ``triplet_completion``.
        datasets:
            Optional list of dataset names to scope search.
        top_k:
            Maximum number of results.
        """
        import cognee

        st = _SEARCH_TYPE_MAP.get(search_type, SearchType.GRAPH_COMPLETION)
        kwargs: dict[str, Any] = {
            "query_text": query,
            "query_type": st,
            "top_k": top_k,
        }
        if datasets:
            kwargs["datasets"] = datasets

        results = await cognee.search(**kwargs)

        return [
            {
                "result": r.search_result,
                "dataset_id": str(r.dataset_id) if r.dataset_id else None,
                "dataset_name": r.dataset_name,
            }
            for r in results
        ]

    # ── Graph query operations ──────────────────────────────────

    async def list_entities(
        self,
        *,
        type_name: str | None = None,
        name: str | None = None,
    ) -> list[dict[str, Any]]:
        """List entities from the knowledge graph.

        Parameters
        ----------
        type_name:
            Filter by entity type name (e.g. ``"Person"``).
        name:
            Filter by entity name (substring match).
        """
        from cognee.infrastructure.databases.graph import get_graph_engine

        engine = await get_graph_engine()
        nodes_and_edges = await engine.get_graph_data()
        nodes = nodes_and_edges[0]  # list of (id, properties) tuples

        results: list[dict[str, Any]] = []
        for node_id, props in nodes:
            if type_name and props.get("type") != type_name:
                continue
            if name and name.lower() not in (props.get("name") or "").lower():
                continue
            results.append({"id": str(node_id), **props})

        return results

    async def list_facts(
        self,
        *,
        entity_id: str | None = None,
        relationship_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """List relationships (facts) from the knowledge graph.

        Parameters
        ----------
        entity_id:
            If provided, only return edges connected to this node.
        relationship_type:
            If provided, filter by relationship name.
        """
        from cognee.infrastructure.databases.graph import get_graph_engine

        engine = await get_graph_engine()

        if entity_id:
            edges = await engine.get_edges(entity_id)
        else:
            _, edges = await engine.get_graph_data()

        results: list[dict[str, Any]] = []
        for edge in edges:
            # edges are (source_id, target_id, rel_name, properties) tuples
            source_id, target_id, rel_name, props = edge
            if relationship_type and rel_name != relationship_type:
                continue
            results.append(
                {
                    "source_id": str(source_id),
                    "target_id": str(target_id),
                    "relationship": rel_name,
                    "properties": props or {},
                }
            )

        return results

    # ── Graph mutation operations ───────────────────────────────

    async def update_entity(
        self,
        entity_id: str,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        """Update properties on a graph node.

        Parameters
        ----------
        entity_id:
            The node ID to update.
        fields:
            Dictionary of field names and new values.
        """
        from cognee.infrastructure.databases.graph import get_graph_engine

        engine = await get_graph_engine()
        node = await engine.get_node(entity_id)
        if node is None:
            return {"status": "error", "reason": f"entity {entity_id} not found"}

        # Build updated properties, then delete+re-add with rollback on failure
        updated_props = {**node, **fields}
        await engine.delete_node(entity_id)
        try:
            await engine.add_node(entity_id, properties=updated_props)
        except Exception:
            # Restore original node on failure
            await engine.add_node(entity_id, properties=node)
            raise

        return {"status": "ok", "entity_id": entity_id, "updated_fields": list(fields.keys())}

    async def merge_entities(
        self,
        entity_ids: list[str],
    ) -> dict[str, Any]:
        """Merge multiple entities into one.

        The first entity in the list is the survivor.  All edges from other
        entities are re-pointed to the survivor, then the duplicates are
        deleted.

        Parameters
        ----------
        entity_ids:
            List of node IDs to merge.  First becomes the survivor.
        """
        if len(entity_ids) < 2:
            return {"status": "error", "reason": "need at least 2 entity IDs to merge"}

        from cognee.infrastructure.databases.graph import get_graph_engine

        engine = await get_graph_engine()
        survivor_id = entity_ids[0]

        # Re-point edges from duplicates to survivor.
        for dup_id in entity_ids[1:]:
            edges = await engine.get_edges(dup_id)
            for source_id, target_id, rel_name, props in edges:
                new_source = survivor_id if str(source_id) == str(dup_id) else str(source_id)
                new_target = survivor_id if str(target_id) == str(dup_id) else str(target_id)
                if new_source == new_target:
                    continue  # skip self-loops from merge
                await engine.add_edge(new_source, new_target, rel_name, props)
            await engine.delete_node(dup_id)

        return {
            "status": "ok",
            "survivor_id": survivor_id,
            "merged_count": len(entity_ids) - 1,
        }

    async def delete(self, node_id: str) -> dict[str, Any]:
        """Delete a node from the knowledge graph.

        Parameters
        ----------
        node_id:
            The node ID to delete.
        """
        from cognee.infrastructure.databases.graph import get_graph_engine

        engine = await get_graph_engine()
        await engine.delete_node(node_id)
        return {"status": "ok", "deleted_id": node_id}

    async def build_communities(self) -> dict[str, Any]:
        """Trigger community detection and summary building via memify.

        Returns a status report.
        """
        import cognee

        await cognee.memify()
        return {"status": "ok", "action": "community_summaries_built"}
