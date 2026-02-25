"""Knowledge graph MCP sub-server — Cognee document knowledge base.

Exposes knowledge tools (search, ingest, entities, facts, update, merge,
delete, communities) that delegate to the daemon's CogneeBackend.

All tools return natural language strings for agent readability.

IMPORTANT: Do NOT use ``from __future__ import annotations`` in this file.
It breaks Pydantic's runtime ``Annotated`` resolution for JSON schema generation.
"""

import json
import logging
from typing import Annotated

from fastmcp import Context, FastMCP
from pydantic import Field

from ._helpers import get_daemon, make_lifespan

logger = logging.getLogger(__name__)


def _visibility(ctx: Context) -> str:
    return ctx.fastmcp._lifespan_result["visibility"]


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


def _fmt_facts(facts: list[dict]) -> str:
    """Format relationship list into numbered lines."""
    if not facts:
        return "No relationships found."
    lines = []
    for i, f in enumerate(facts, 1):
        src = str(f.get("source_id", "?"))[:8]
        tgt = str(f.get("target_id", "?"))[:8]
        rel = f.get("relationship", "related_to")
        props = f.get("properties", {})
        prop_str = ""
        if props:
            prop_str = f" {props}"
        lines.append(f"  {i}. [{src}] --{rel}--> [{tgt}]{prop_str}")
    return "\n".join(lines)


def create_knowledge_server(daemon, visibility: str = "master") -> FastMCP:
    """Create the knowledge graph MCP sub-server (Cognee).

    Args:
        daemon: CentralHubDaemon instance.
        visibility: Access level for tool filtering.
            ``"master"`` gets all tools (search, ingest, graph mutation).
            ``"all"`` gets ``knowledge_search`` only.
    """
    server = FastMCP("Knowledge", lifespan=make_lifespan(daemon, visibility=visibility))

    # -- knowledge_search (available to all visibility levels) -------------

    @server.tool()
    async def knowledge_search(
        query: Annotated[
            str,
            Field(description="Natural language query to search the document knowledge graph."),
        ],
        search_type: Annotated[
            str,
            Field(
                description=(
                    "Search strategy: 'graph_completion' (default, graph-augmented), "
                    "'chunks' (raw text chunks), 'summaries' (community summaries), "
                    "'rag_completion' (RAG with vector), 'natural_language' (NL query over graph), "
                    "'triplet_completion' (triple-based)."
                ),
            ),
        ] = "graph_completion",
        datasets: Annotated[
            str | None,
            Field(
                description="Comma-separated dataset names to scope search. None searches all.",
            ),
        ] = None,
        ctx: Context = None,
    ) -> str:
        """Search the document knowledge graph.

        Queries Cognee's knowledge graph built from ingested documents.
        Returns ranked results based on the chosen search strategy.
        """
        d = get_daemon(ctx)
        backend = d.cognee_backend
        if backend is None or not backend.ready:
            return "Error: Knowledge service not available."

        ds_list = [s.strip() for s in datasets.split(",")] if datasets else None

        try:
            results = await backend.search(
                query,
                search_type=search_type,
                datasets=ds_list,
            )
        except Exception as exc:
            return f"Error: {exc}"

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
            # Truncate long results
            if len(str(content)) > 300:
                content = str(content)[:297] + "..."
            lines.append(f"  {i}.{suffix} {content}")

        return f"Results ({len(results)}):\n" + "\n".join(lines)

    # -- Master-only tools ------------------------------------------------

    if visibility == "master":

        @server.tool()
        async def knowledge_ingest(
            content_or_path: Annotated[
                str,
                Field(
                    description=(
                        "Raw text content or absolute file path to ingest. "
                        "Files are chunked, entities extracted, and added to the knowledge graph."
                    ),
                ),
            ],
            dataset: Annotated[
                str,
                Field(description="Dataset name to store under (default 'knowledge')."),
            ] = "knowledge",
            tags: Annotated[
                str | None,
                Field(description="Comma-separated tags for organization (e.g. 'music,research')."),
            ] = None,
            ctx: Context = None,
        ) -> str:
            """Ingest a document or text into the knowledge graph.

            Runs the full Cognee pipeline: chunking, entity extraction using
            8 DataPoint types (Person, Band, Organization, Project, Event,
            Concept, Genre, Document), graph building, and temporal awareness.
            """
            d = get_daemon(ctx)
            backend = d.cognee_backend
            if backend is None or not backend.ready:
                return "Error: Knowledge service not available."

            tag_list = [t.strip() for t in tags.split(",")] if tags else None

            try:
                result = await backend.ingest(
                    content_or_path,
                    dataset=dataset,
                    tags=tag_list,
                )
            except Exception as exc:
                return f"Error: {exc}"

            status = result.get("status", "unknown")
            ds = result.get("dataset", dataset)
            tag_info = f", tags: {result.get('tags', [])}" if result.get("tags") else ""
            return f"Ingested into '{ds}' (status: {status}{tag_info})"

        @server.tool()
        async def knowledge_entities(
            type_name: Annotated[
                str | None,
                Field(
                    description=(
                        "Filter by entity type: 'Person', 'Band', 'Organization', "
                        "'Project', 'Event', 'Concept', 'Genre', 'Document'. None returns all."
                    ),
                ),
            ] = None,
            name: Annotated[
                str | None,
                Field(description="Filter by entity name (substring match)."),
            ] = None,
            ctx: Context = None,
        ) -> str:
            """Browse entities in the knowledge graph.

            Returns a list of graph nodes with their types, names, and descriptions.
            Use this to explore what the knowledge base contains or find entities
            to update/merge/delete.
            """
            d = get_daemon(ctx)
            backend = d.cognee_backend
            if backend is None or not backend.ready:
                return "Error: Knowledge service not available."

            try:
                entities = await backend.list_entities(
                    type_name=type_name,
                    name=name,
                )
            except Exception as exc:
                return f"Error: {exc}"

            if not entities:
                return "No entities found."

            return f"Entities ({len(entities)}):\n{_fmt_entities(entities)}"

        @server.tool()
        async def knowledge_facts(
            entity_id: Annotated[
                str | None,
                Field(description="Filter by entity ID — shows edges connected to this node."),
            ] = None,
            relationship_type: Annotated[
                str | None,
                Field(description="Filter by relationship type name."),
            ] = None,
            ctx: Context = None,
        ) -> str:
            """Browse relationships (facts) in the knowledge graph.

            Returns edges connecting entities — each with source, target,
            relationship type, and properties. Use ``entity_id`` to see all
            connections for a specific entity.
            """
            d = get_daemon(ctx)
            backend = d.cognee_backend
            if backend is None or not backend.ready:
                return "Error: Knowledge service not available."

            try:
                facts = await backend.list_facts(
                    entity_id=entity_id,
                    relationship_type=relationship_type,
                )
            except Exception as exc:
                return f"Error: {exc}"

            if not facts:
                return "No relationships found."

            return f"Relationships ({len(facts)}):\n{_fmt_facts(facts)}"

        @server.tool()
        async def knowledge_update(
            entity_id: Annotated[
                str,
                Field(description="ID of the entity to update (from knowledge_entities results)."),
            ],
            fields: Annotated[
                str,
                Field(
                    description=(
                        "JSON object of fields to update (e.g. "
                        '\'{"name": "New Name", "description": "Updated desc"}\').'
                    ),
                ),
            ],
            ctx: Context = None,
        ) -> str:
            """Update properties on a knowledge graph entity.

            Pass ``fields`` as a JSON string with the properties to change.
            Use ``knowledge_entities`` first to find the entity ID.
            """
            d = get_daemon(ctx)
            backend = d.cognee_backend
            if backend is None or not backend.ready:
                return "Error: Knowledge service not available."

            try:
                field_dict = json.loads(fields)
            except json.JSONDecodeError as exc:
                return f"Error: Invalid JSON in fields: {exc}"

            try:
                result = await backend.update_entity(entity_id, field_dict)
            except Exception as exc:
                return f"Error: {exc}"

            status = result.get("status", "unknown")
            if status == "error":
                return f"Error: {result.get('reason', 'unknown')}"

            updated = result.get("updated_fields", [])
            return f"Updated entity {entity_id[:12]}: {', '.join(updated)}"

        @server.tool()
        async def knowledge_merge(
            entity_ids: Annotated[
                str,
                Field(
                    description=(
                        "Comma-separated entity IDs to merge. First ID becomes the survivor — "
                        "all edges from other entities are re-pointed to it, then duplicates deleted."
                    ),
                ),
            ],
            ctx: Context = None,
        ) -> str:
            """Merge duplicate entities in the knowledge graph.

            The first entity ID in the list survives. All edges from duplicate
            entities are re-pointed to the survivor, then the duplicates are
            deleted. Use ``knowledge_entities`` to identify duplicates first.
            """
            d = get_daemon(ctx)
            backend = d.cognee_backend
            if backend is None or not backend.ready:
                return "Error: Knowledge service not available."

            ids = [s.strip() for s in entity_ids.split(",") if s.strip()]
            if len(ids) < 2:
                return "Error: Need at least 2 entity IDs to merge (comma-separated)."

            try:
                result = await backend.merge_entities(ids)
            except Exception as exc:
                return f"Error: {exc}"

            status = result.get("status", "unknown")
            if status == "error":
                return f"Error: {result.get('reason', 'unknown')}"

            survivor = result.get("survivor_id", ids[0])[:12]
            merged = result.get("merged_count", len(ids) - 1)
            return f"Merged {merged} entities into {survivor}"

        @server.tool()
        async def knowledge_delete(
            node_id: Annotated[
                str,
                Field(description="ID of the node to delete from the knowledge graph."),
            ],
            ctx: Context = None,
        ) -> str:
            """Delete a node from the knowledge graph.

            Permanently removes the entity and all its edges. Use
            ``knowledge_entities`` or ``knowledge_facts`` to find the ID first.
            """
            d = get_daemon(ctx)
            backend = d.cognee_backend
            if backend is None or not backend.ready:
                return "Error: Knowledge service not available."

            try:
                result = await backend.delete(node_id)
            except Exception as exc:
                return f"Error: {exc}"

            return f"Deleted: {result.get('deleted_id', node_id)[:12]}"

        @server.tool()
        async def knowledge_communities(
            ctx: Context = None,
        ) -> str:
            """Trigger community detection and summary building.

            Runs Cognee's memify pass to detect entity communities and
            generate summaries. Use this after significant ingestion to
            improve ``knowledge_search`` with summary-based results.
            """
            d = get_daemon(ctx)
            backend = d.cognee_backend
            if backend is None or not backend.ready:
                return "Error: Knowledge service not available."

            try:
                result = await backend.build_communities()
            except Exception as exc:
                return f"Error: {exc}"

            return f"Community summaries built (status: {result.get('status', 'ok')})"

    return server
