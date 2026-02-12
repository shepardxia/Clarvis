"""Memory MCP sub-server — mounted onto the main Clarvis server.

Exposes memory tools (add, search, cognify, status, check_in) that call
the daemon's CogneeMemoryService and ContextAccumulator directly (in-process).

All tools return natural language strings for agent readability.
"""

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Annotated

from fastmcp import Context, FastMCP
from pydantic import Field

if TYPE_CHECKING:
    from .daemon import CentralHubDaemon


def _daemon(ctx: Context) -> "CentralHubDaemon":
    return ctx.fastmcp._lifespan_result["daemon"]


VALID_DATASETS = {"shepard", "clarvis", "academic"}


def _validate_dataset(name: str) -> str | None:
    """Return error message if dataset name is invalid, else None."""
    if name not in VALID_DATASETS:
        return f"Unknown dataset '{name}'. Valid: {', '.join(sorted(VALID_DATASETS))}"
    return None


async def memory_add(
    data: Annotated[
        str,
        Field(description="Text content to store in the knowledge graph. Should be atomic and specific."),
    ],
    dataset: Annotated[
        str,
        Field(
            description=(
                "Dataset to store in. Three domains:"
                " 'shepard' (personal — preferences, taste, project decisions),"
                " 'clarvis' (Clarvis's own thoughts, observations, companion memory),"
                " 'academic' (intellectual — AI/cog sci, philosophy, papers, research)."
            )
        ),
    ] = "shepard",
    ctx: Context = None,
) -> str:
    """Add content to the Clarvis knowledge graph.

    Best used with curated, atomic facts — not raw session dumps.
    Examples:
      - "The TOTP auth fix in clautify requires both sp_dc cookie AND TOTP params"
      - "User prefers blackgaze over post-punk recommendations"

    After adding items, call memory_cognify to process them into the graph.
    """
    if err := _validate_dataset(dataset):
        return f"Error: {err}"
    d = _daemon(ctx)
    if not d.memory_service:
        return "Error: Memory service not initialized."
    result = await d.memory_service.add(data, dataset)
    if "error" in result:
        return f"Error: {result['error']}"
    return f"Added to {dataset}."


async def memory_search(
    query: Annotated[
        str,
        Field(description="Natural language query to search the knowledge graph."),
    ],
    search_type: Annotated[
        str,
        Field(
            description=(
                "Search type: GRAPH_COMPLETION (rich, ~3s),"
                " SUMMARIES (cheap overviews, ~300ms), CHUNKS (raw text, ~300ms)."
            )
        ),
    ] = "GRAPH_COMPLETION",
    top_k: Annotated[
        int,
        Field(description="Maximum number of results to return."),
    ] = 10,
    datasets: Annotated[
        list[str] | None,
        Field(description=("Restrict search to specific datasets (shepard, clarvis, academic). Omit to search all.")),
    ] = None,
    ctx: Context = None,
) -> str:
    """Search the Clarvis knowledge graph.

    Use GRAPH_COMPLETION for contextual answers that leverage entity
    relationships, SUMMARIES for cheap overviews, or CHUNKS for raw text.
    """
    d = _daemon(ctx)
    if not d.memory_service:
        return "Error: Memory service not initialized."
    results = await d.memory_service.search(query, search_type, top_k, datasets=datasets)
    if not results:
        return "No results."
    if isinstance(results[0], dict) and "error" in results[0]:
        return f"Error: {results[0]['error']}"
    lines = []
    for i, item in enumerate(results, 1):
        if isinstance(item, dict):
            text = item.get("text") or item.get("name") or item.get("result") or str(item)
        else:
            text = str(item)
        lines.append(f"  {i}. {text}")
    return "\n".join(lines)


async def memory_cognify(
    dataset: Annotated[
        str,
        Field(description="Dataset to process into the knowledge graph."),
    ] = "shepard",
    ctx: Context = None,
) -> str:
    """Trigger entity extraction and graph building for pending memory items.

    Call this after adding content with memory_add to process raw text
    into structured entities and relationships in the knowledge graph.
    """
    if err := _validate_dataset(dataset):
        return f"Error: {err}"
    d = _daemon(ctx)
    if not d.memory_service:
        return "Error: Memory service not initialized."
    result = await d.memory_service.cognify(dataset)
    if "error" in result:
        return f"Error: {result['error']}"
    return f"Cognified {dataset}."


async def memory_status(
    ctx: Context = None,
) -> str:
    """Get memory service status — readiness and dataset item counts."""
    d = _daemon(ctx)
    if not d.memory_service:
        return "Error: Memory service not initialized."
    info = await d.memory_service.status()
    if "error" in info:
        return f"Error: {info['error']}"
    if not info.get("ready"):
        return "Memory service not ready."
    ds_list = info.get("datasets", [])
    parts = [f"{ds['name']} ({ds['item_count']})" for ds in ds_list]
    return f"Ready. Datasets: {', '.join(parts) or 'none'}."


async def memory_list(
    dataset: Annotated[
        str,
        Field(description="Dataset to list items from (shepard, clarvis, or academic)."),
    ] = "shepard",
    ctx: Context = None,
) -> str:
    """List data items in a dataset with content previews and IDs.

    Use this to identify items before deleting with memory_delete.
    """
    if err := _validate_dataset(dataset):
        return f"Error: {err}"
    d = _daemon(ctx)
    if not d.memory_service:
        return "Error: Memory service not initialized."
    items = await d.memory_service.list_items(dataset)
    if not items:
        return f"{dataset}: empty."
    if isinstance(items[0], dict) and "error" in items[0]:
        return f"Error: {items[0]['error']}"
    lines = [f"{dataset} ({len(items)} items):"]
    for item in items:
        preview = item.get("preview") or "?"
        date = (item.get("created_at") or "")[:10]
        lines.append(f'  {item["data_id"]} — "{preview}" ({date})')
    return "\n".join(lines)


async def memory_delete(
    data_id: Annotated[
        str,
        Field(description="UUID of the data item to delete (from memory_list)."),
    ],
    dataset: Annotated[
        str,
        Field(description="Dataset containing the item (shepard, clarvis, or academic)."),
    ],
    mode: Annotated[
        str,
        Field(description="'soft' (default) keeps orphaned entities, 'hard' removes them too."),
    ] = "soft",
    ctx: Context = None,
) -> str:
    """Delete a specific data item from the knowledge graph.

    Use memory_list first to find the data_id. Soft mode keeps extracted
    entities; hard mode also removes entities with no other connections.
    """
    if err := _validate_dataset(dataset):
        return f"Error: {err}"
    d = _daemon(ctx)
    if not d.memory_service:
        return "Error: Memory service not initialized."
    result = await d.memory_service.delete(data_id, dataset, mode=mode)
    if "error" in result:
        return f"Error: {result['error']}"
    return f"Deleted {data_id} from {dataset}."


async def check_in(
    ctx: Context = None,
) -> str:
    """Returns accumulated context since the last check-in.

    Shows completed sessions (with conversation previews), staged items,
    and relevant existing memories. Use at the start of a memory check-in
    to see what happened since last time.

    After reviewing, use memory_add with curated facts worth keeping,
    then memory_cognify to process them into the graph.
    """
    d = _daemon(ctx)
    if not d.context_accumulator:
        return "Error: Context accumulator not available."

    pending = d.context_accumulator.get_pending()
    sessions = pending.get("sessions_since_last", [])
    staged = pending.get("staged_items", [])
    last_ts = pending.get("last_check_in", "unknown")

    lines = [f"Last check-in: {last_ts[:16] if len(last_ts) > 16 else last_ts}"]

    # Sessions
    if sessions:
        lines.append(f"\n{len(sessions)} session(s) since:")
        for s in sessions:
            ts = (s.get("timestamp") or "")[:16]
            lines.append(f"\n  {s.get('project', '?')} ({ts})")
            preview = s.get("preview", "")
            if preview:
                for pline in preview.split("\n"):
                    lines.append(f"    {pline}")
    else:
        lines.append("\nNo sessions since last check-in.")

    # Staged items
    if staged:
        lines.append(f"\n{len(staged)} staged item(s):")
        for item in staged:
            ts = (item.get("timestamp") or "")[:16]
            lines.append(f"  - {item.get('content', '?')} ({ts})")

    # Relevant memories
    svc = d.memory_service
    if svc and svc._ready and sessions:
        try:
            projects = {s.get("project", "") for s in sessions if s.get("project")}
            query = " ".join(projects) if projects else "recent work"
            memories = await svc.search(query, "GRAPH_COMPLETION", 5)
            if memories and not (isinstance(memories[0], dict) and "error" in memories[0]):
                lines.append("\nRelevant memories:")
                for i, m in enumerate(memories, 1):
                    if isinstance(m, dict):
                        text = m.get("text") or m.get("result") or str(m)
                    else:
                        text = str(m)
                    lines.append(f"  {i}. {text}")
        except Exception:
            pass

    return "\n".join(lines)


async def mark_checked_in(
    ctx: Context = None,
) -> str:
    """Clear the check-in queue after review is complete.

    Call this after you've reviewed the check_in bundle and memory_add'd
    the facts worth keeping. Advances the watermark and clears staged items.
    """
    d = _daemon(ctx)
    if not d.context_accumulator:
        return "Error: Context accumulator not available."
    d.context_accumulator.mark_checked_in()
    return "Check-in complete, queue cleared."


async def memory_graph_traverse(
    entity: Annotated[
        str,
        Field(
            description=(
                "Entity name to search for (substring match)."
                " Use a name from memory_graph_overview or a previous traverse."
            )
        ),
    ],
    max_connections: Annotated[
        int,
        Field(description="Maximum connections to return per entity."),
    ] = 50,
    ctx: Context = None,
) -> str:
    """Traverse the knowledge graph from a named entity.

    Finds entities matching the name and returns their direct connections.
    Follow connections by traversing returned entity names.
    """
    d = _daemon(ctx)
    if not d.memory_service:
        return "Error: Memory service not initialized."
    result = await d.memory_service.graph_traverse(entity, max_connections)
    if "error" in result:
        return f"Error: {result['error']}"
    matches = result.get("matches", [])
    if not matches:
        return result.get("hint", "No entities found.")
    lines = []
    for m in matches:
        node = m["node"]
        lines.append(f"{node['name']} ({node['type']}) [{node['id']}]")
        for c in m.get("connections", []):
            t = c["target"]
            lines.append(f"  —{c['relationship']}→ {t['name']} ({t['type']})")
    return "\n".join(lines)


async def memory_graph_query(
    cypher: Annotated[
        str,
        Field(
            description=(
                "Cypher query to execute (read-only — no CREATE/DELETE/SET)."
                " Nodes are :Node with properties (id, name, type)."
                " Edges are :EDGE with property relationship_name."
            )
        ),
    ],
    ctx: Context = None,
) -> str:
    """Execute a raw Cypher query against the knowledge graph (Kuzu dialect).

    Example: MATCH (n:Node)-[r:EDGE]-(m:Node) WHERE n.name = 'X'
    RETURN n.name, r.relationship_name, m.name
    """
    d = _daemon(ctx)
    if not d.memory_service:
        return "Error: Memory service not initialized."
    rows = await d.memory_service.graph_query(cypher)
    if not rows:
        return "No results."
    if isinstance(rows[0], dict) and "error" in rows[0]:
        return f"Error: {rows[0]['error']}"
    lines = [str(row) for row in rows]
    return f"{len(rows)} rows:\n" + "\n".join(f"  {line}" for line in lines)


async def memory_graph_overview(
    ctx: Context = None,
) -> str:
    """Get an overview of the knowledge graph — node/edge counts, entity
    names, and relationship type frequencies. Use to orient before traversing.
    """
    d = _daemon(ctx)
    if not d.memory_service:
        return "Error: Memory service not initialized."
    info = await d.memory_service.graph_overview()
    if "error" in info:
        return f"Error: {info['error']}"
    lines = [f"{info['node_count']} nodes, {info['edge_count']} edges."]
    entities = info.get("entities", [])
    if entities:
        names = [e["name"] for e in entities[:50]]
        line = f"Entities: {', '.join(names)}"
        if len(entities) > 50:
            line += f" ... and {len(entities) - 50} more"
        lines.append(line)
    rels = info.get("relationship_types", [])
    if rels:
        parts = [f"{r['type']} x{r['count']}" for r in rels]
        lines.append(f"Relationships: {', '.join(parts)}")
    return "\n".join(lines)


async def memory_graph_delete_node(
    node_id: Annotated[
        str,
        Field(
            description=("UUID of the node to delete (from memory_graph_traverse or memory_graph_overview results).")
        ),
    ],
    ctx: Context = None,
) -> str:
    """Delete a node and all its edges from the knowledge graph.

    Also cleans up vector embeddings and marks ledger entries as deleted.
    Use memory_graph_traverse or memory_graph_overview first to find the node ID.
    """
    d = _daemon(ctx)
    if not d.memory_service:
        return "Error: Memory service not initialized."
    result = await d.memory_service.graph_delete_node(node_id)
    if "error" in result:
        return f"Error: {result['error']}"
    deleted = result.get("deleted", {})
    return f"Deleted {deleted.get('name', node_id)} ({deleted.get('type', '?')})."


_TOOLS = [
    memory_add,
    memory_search,
    memory_cognify,
    memory_status,
    memory_list,
    memory_delete,
    check_in,
    mark_checked_in,
    memory_graph_traverse,
    memory_graph_query,
    memory_graph_overview,
    memory_graph_delete_node,
]


def create_memory_server(daemon):
    """Create the memory MCP sub-server."""

    @asynccontextmanager
    async def memory_lifespan(server):
        yield {"daemon": daemon}

    srv = FastMCP("memory", lifespan=memory_lifespan)
    for fn in _TOOLS:
        srv.tool()(fn)
    return srv
