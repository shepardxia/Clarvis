"""Cognee knowledge graph backend.

Thin wrapper around cognee's pip API for document ingestion, knowledge graph
construction, and graph queries.  Configures cognee with PostgreSQL (relational
+ vector via pgvector) and kuzu (embedded graph) backends.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

from cognee.api.v1.search import SearchType

from .entity_types import ENTITY_TYPES

logger = logging.getLogger(__name__)


# ── Formatting helpers ─────────────────────────────────────────


def _fmt_entities(entities: list[dict]) -> str:
    """Format entity list into numbered lines."""
    if not entities:
        return "No entities found."
    lines = []
    for i, e in enumerate(entities, 1):
        eid = str(e.get("id", "?"))[:12]
        name = e.get("name", "unnamed")
        etype = e.get("type", "")
        desc = e.get("description") or ""
        parts = [f"[{etype}]" if etype else "", name]
        if desc:
            preview = desc[:60] + ("..." if len(desc) > 60 else "")
            parts.append(f"-- {preview}")
        line = " ".join(p for p in parts if p)
        lines.append(f"  {i}. [id:{eid}] {line}")
    return "\n".join(lines)


def _fmt_relations(rels: list[dict]) -> str:
    """Format relationship list into numbered lines."""
    if not rels:
        return "No relationships found."
    lines = []
    for i, r in enumerate(rels, 1):
        src = str(r.get("source_id", "?"))[:8]
        tgt = str(r.get("target_id", "?"))[:8]
        rel = r.get("relationship", "related_to")
        props = r.get("properties", {})
        prop_str = ""
        if props:
            prop_str = f" {props}"
        lines.append(f"  {i}. [{src}] --{rel}--> [{tgt}]{prop_str}")
    return "\n".join(lines)


def _fmt_search_results(results: list[dict]) -> str:
    """Format knowledge search results into numbered lines."""
    if not results:
        return "No results found."
    lines = []
    for i, r in enumerate(results, 1):
        content = r.get("result", str(r))
        ds_name = r.get("dataset_name", "")
        if isinstance(content, dict):
            content = json.dumps(content, default=str, ensure_ascii=False)
        elif isinstance(content, list):
            content = "; ".join(str(x) for x in content)
        suffix = f" [{ds_name}]" if ds_name else ""
        content = str(content)
        if len(content) > 300:
            content = content[:297] + "..."
        lines.append(f"  {i}.{suffix} {content}")
    return f"Results ({len(results)}):\n" + "\n".join(lines)


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
        format: bool = False,
    ) -> dict[str, Any] | str:
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
        format:
            If True, return a formatted string instead of raw dict.
        """
        import cognee

        await cognee.add(content_or_path, dataset_name=dataset)
        await cognee.cognify(
            datasets=[dataset],
            graph_model=list(ENTITY_TYPES.values()),
        )

        result = {
            "status": "ok",
            "dataset": dataset,
            "tags": tags or [],
        }
        if format:
            tag_info = f", tags: {result['tags']}" if result["tags"] else ""
            return f"Ingested into '{dataset}' (status: ok{tag_info})"
        return result

    # ── Search ──────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        *,
        search_type: str = "graph_completion",
        datasets: list[str] | None = None,
        top_k: int = 10,
        format: bool = False,
    ) -> list[dict[str, Any]] | str:
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
        format:
            If True, return a formatted string instead of raw dicts.
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

        items = [
            {
                "result": r.search_result,
                "dataset_id": str(r.dataset_id) if r.dataset_id else None,
                "dataset_name": r.dataset_name,
            }
            for r in results
        ]
        return _fmt_search_results(items) if format else items

    # ── Graph query operations ──────────────────────────────────

    async def list_entities(
        self,
        *,
        type_name: str | None = None,
        name: str | None = None,
        format: bool = False,
    ) -> list[dict[str, Any]] | str:
        """List entities from the knowledge graph.

        Parameters
        ----------
        type_name:
            Filter by entity type name (e.g. ``"Person"``).
        name:
            Filter by entity name (substring match).
        format:
            If True, return a formatted string instead of raw dicts.
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

        if format:
            if not results:
                return "No entities found."
            return f"Entities ({len(results)}):\n{_fmt_entities(results)}"
        return results

    async def list_facts(
        self,
        *,
        entity_id: str | None = None,
        relationship_type: str | None = None,
        format: bool = False,
    ) -> list[dict[str, Any]] | str:
        """List relationships (facts) from the knowledge graph.

        Parameters
        ----------
        entity_id:
            If provided, only return edges connected to this node.
        relationship_type:
            If provided, filter by relationship name.
        format:
            If True, return a formatted string instead of raw dicts.
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

        if format:
            if not results:
                return "No relationships found."
            return f"Relationships ({len(results)}):\n{_fmt_relations(results)}"
        return results

    # ── Graph mutation operations ───────────────────────────────

    async def update_entity(
        self,
        entity_id: str,
        fields: dict[str, Any],
        *,
        format: bool = False,
    ) -> dict[str, Any] | str:
        """Update properties on a graph node.

        Parameters
        ----------
        entity_id:
            The node ID to update.
        fields:
            Dictionary of field names and new values.
        format:
            If True, return a formatted string instead of raw dict.
        """
        from cognee.infrastructure.databases.graph import get_graph_engine

        engine = await get_graph_engine()
        node = await engine.get_node(entity_id)
        if node is None:
            reason = f"entity {entity_id} not found"
            if format:
                return f"Error: {reason}"
            return {"status": "error", "reason": reason}

        # GraphDBInterface has no update_node method, so we must delete+re-add.
        # Save edges first so they survive the node deletion.
        updated_props = {**node, **fields}
        edges = await engine.get_edges(entity_id)
        await engine.delete_node(entity_id)
        try:
            await engine.add_node(entity_id, properties=updated_props)
        except Exception:
            # Restore original node on failure
            await engine.add_node(entity_id, properties=node)
            raise
        finally:
            # Restore all edges that were connected to this node
            for source_id, target_id, rel_name, props in edges:
                await engine.add_edge(str(source_id), str(target_id), rel_name, props)

        result = {"status": "ok", "entity_id": entity_id, "updated_fields": list(fields.keys())}
        if format:
            return f"Updated entity {entity_id[:12]}: {', '.join(result['updated_fields'])}"
        return result

    async def merge_entities(
        self,
        entity_ids: list[str],
        *,
        format: bool = False,
    ) -> dict[str, Any] | str:
        """Merge multiple entities into one.

        The first entity in the list is the survivor.  All edges from other
        entities are re-pointed to the survivor, then the duplicates are
        deleted.

        Parameters
        ----------
        entity_ids:
            List of node IDs to merge.  First becomes the survivor.
        format:
            If True, return a formatted string instead of raw dict.
        """
        if len(entity_ids) < 2:
            reason = "need at least 2 entity IDs to merge"
            if format:
                return f"Error: {reason}"
            return {"status": "error", "reason": reason}

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

        result = {
            "status": "ok",
            "survivor_id": survivor_id,
            "merged_count": len(entity_ids) - 1,
        }
        if format:
            return f"Merged {result['merged_count']} entities into {survivor_id[:12]}"
        return result

    async def delete(self, node_id: str, *, format: bool = False) -> dict[str, Any] | str:
        """Delete a node from the knowledge graph.

        Parameters
        ----------
        node_id:
            The node ID to delete.
        format:
            If True, return a formatted string instead of raw dict.
        """
        from cognee.infrastructure.databases.graph import get_graph_engine

        engine = await get_graph_engine()
        await engine.delete_node(node_id)
        result = {"status": "ok", "deleted_id": node_id}
        if format:
            return f"Deleted: {node_id[:12]}"
        return result

    async def build_communities(self, *, format: bool = False) -> dict[str, Any] | str:
        """Trigger community detection and summary building via memify.

        Parameters
        ----------
        format:
            If True, return a formatted string instead of raw dict.
        """
        import cognee

        await cognee.memify()
        result = {"status": "ok", "action": "community_summaries_built"}
        if format:
            return "Community summaries built (status: ok)"
        return result
