"""Memory MCP sub-server — mounted onto the main Clarvis server.

Exposes memory tools (add, search, cognify, status, check_in) that call
the daemon's CogneeMemoryService and ContextAccumulator directly (in-process).
"""

import json
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Annotated

from fastmcp import Context, FastMCP
from pydantic import Field

if TYPE_CHECKING:
    from .daemon import CentralHubDaemon


def _daemon(ctx: Context) -> "CentralHubDaemon":
    return ctx.fastmcp._lifespan_result["daemon"]


# --- Tool implementations ---


async def memory_add(
    data: Annotated[
        str,
        Field(description="Text content to store in the knowledge graph. Should be atomic and specific."),
    ],
    dataset: Annotated[
        str,
        Field(
            description=(
                "Dataset to store in. Two domains: 'shepard' (personal — preferences,"
                " taste, project decisions) or 'academic' (intellectual — AI/cog sci,"
                " philosophy, papers, research)."
            )
        ),
    ] = "shepard",
    ctx: Context = None,
) -> dict:
    """Add content to the Clarvis knowledge graph.

    Best used with curated, atomic facts — not raw session dumps.
    Examples:
      - "The TOTP auth fix in clautify requires both sp_dc cookie AND TOTP params"
      - "User prefers blackgaze over post-punk recommendations"

    After adding items, call memory_cognify to process them into the graph.
    """
    d = _daemon(ctx)
    if not d.memory_service:
        return {"error": "Memory service not initialized"}
    return await d.memory_service.add(data, dataset)


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
        Field(
            description=(
                "Restrict search to specific datasets. Omit to search all. Use memory_status to see available datasets."
            )
        ),
    ] = None,
    ctx: Context = None,
) -> list:
    """Search the Clarvis knowledge graph.

    Returns a list of matching results from the graph. Use GRAPH_COMPLETION
    for contextual answers that leverage entity relationships, SUMMARIES for
    cheap overviews, or CHUNKS for raw text retrieval.
    """
    d = _daemon(ctx)
    if not d.memory_service:
        return [{"error": "Memory service not initialized"}]
    return await d.memory_service.search(query, search_type, top_k, datasets=datasets)


async def memory_cognify(
    dataset: Annotated[
        str,
        Field(description="Dataset to process into the knowledge graph."),
    ] = "shepard",
    ctx: Context = None,
) -> dict:
    """Trigger entity extraction and graph building for pending memory items.

    Call this after adding content with memory_add to process raw text
    into structured entities and relationships in the knowledge graph.
    """
    d = _daemon(ctx)
    if not d.memory_service:
        return {"error": "Memory service not initialized"}
    return await d.memory_service.cognify(dataset)


async def memory_status(
    ctx: Context = None,
) -> dict:
    """Get memory service status — graph stats, readiness, and pending items."""
    d = _daemon(ctx)
    if not d.memory_service:
        return {"error": "Memory service not initialized"}
    return await d.memory_service.status()


async def check_in(
    ctx: Context = None,
) -> str:
    """Returns accumulated context bundle since the last check-in.

    Includes completed sessions, staged items, and timestamps. Use this
    at the start of a memory check-in conversation to see what happened
    since the last time.

    After reviewing, use memory_add with curated facts worth keeping,
    then memory_cognify to process them into the graph.
    """
    d = _daemon(ctx)
    if not d.context_accumulator:
        return json.dumps({"error": "Context accumulator not available"})

    pending = d.context_accumulator.get_pending()

    # Optionally enrich with relevant existing memories
    svc = d.memory_service
    if svc and svc._ready and pending.get("sessions_since_last"):
        try:
            projects = {s.get("project", "") for s in pending["sessions_since_last"] if s.get("project")}
            query = " ".join(projects) if projects else "recent work"
            memories = await svc.search(query, "GRAPH_COMPLETION", 5)
            pending["relevant_memories"] = memories
        except Exception:
            pending["relevant_memories"] = []
    else:
        pending["relevant_memories"] = []

    return json.dumps(pending, indent=2)


# --- Sub-server factory ---

_TOOLS = [memory_add, memory_search, memory_cognify, memory_status, check_in]


def create_memory_server(daemon):
    """Create the memory MCP sub-server.

    Args:
        daemon: CentralHubDaemon instance (or mock with .memory_service,
            .context_accumulator). Injected into lifespan for tool access.
    """

    @asynccontextmanager
    async def memory_lifespan(server):
        yield {"daemon": daemon}

    srv = FastMCP("memory", lifespan=memory_lifespan)
    for fn in _TOOLS:
        srv.tool()(fn)
    return srv
