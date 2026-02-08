"""Memory MCP sub-server — mounted onto the main Clarvis server.

Exposes memory tools (add, search, cognify, status, check_in) that route
through DaemonClient IPC to the daemon's CogneeMemoryService and ContextAccumulator.
"""

import json
from contextlib import asynccontextmanager
from typing import Annotated

from fastmcp import Context, FastMCP
from pydantic import Field

# --- Tool implementations ---


async def memory_add(
    data: Annotated[
        str,
        Field(description="Text content to store in the knowledge graph. Should be atomic and specific."),
    ],
    dataset: Annotated[
        str,
        Field(description="Dataset namespace for organizing memories."),
    ] = "clarvis",
    ctx: Context = None,
) -> dict:
    """Add content to the Clarvis knowledge graph.

    Best used with curated, atomic facts — not raw session dumps.
    Examples:
      - "The TOTP auth fix in clautify requires both sp_dc cookie AND TOTP params"
      - "User prefers blackgaze over post-punk recommendations"

    After adding items, call memory_cognify to process them into the graph.
    """
    client = ctx.fastmcp._lifespan_result["client"]
    if not client.is_daemon_running():
        return {"error": "Clarvis daemon is not running. Start it with: clarvis start"}
    try:
        return client.call("memory_add", data=data, dataset=dataset)
    except Exception as e:
        return {"error": str(e)}


async def memory_search(
    query: Annotated[
        str,
        Field(description="Natural language query to search the knowledge graph."),
    ],
    search_type: Annotated[
        str,
        Field(description="Cognee search type. GRAPH_COMPLETION uses graph context for richer answers."),
    ] = "GRAPH_COMPLETION",
    top_k: Annotated[
        int,
        Field(description="Maximum number of results to return."),
    ] = 10,
    ctx: Context = None,
) -> list:
    """Search the Clarvis knowledge graph.

    Returns a list of matching results from the graph. Use GRAPH_COMPLETION
    for contextual answers that leverage entity relationships.
    """
    client = ctx.fastmcp._lifespan_result["client"]
    if not client.is_daemon_running():
        return [{"error": "Clarvis daemon is not running. Start it with: clarvis start"}]
    try:
        return client.call("memory_search", query=query, search_type=search_type, top_k=top_k)
    except Exception as e:
        return [{"error": str(e)}]


async def memory_cognify(
    dataset: Annotated[
        str,
        Field(description="Dataset to process into the knowledge graph."),
    ] = "clarvis",
    ctx: Context = None,
) -> dict:
    """Trigger entity extraction and graph building for pending memory items.

    Call this after adding content with memory_add to process raw text
    into structured entities and relationships in the knowledge graph.
    """
    client = ctx.fastmcp._lifespan_result["client"]
    if not client.is_daemon_running():
        return {"error": "Clarvis daemon is not running. Start it with: clarvis start"}
    try:
        return client.call("memory_cognify", dataset=dataset)
    except Exception as e:
        return {"error": str(e)}


async def memory_status(
    ctx: Context = None,
) -> dict:
    """Get memory service status — graph stats, readiness, and pending items."""
    client = ctx.fastmcp._lifespan_result["client"]
    if not client.is_daemon_running():
        return {"error": "Clarvis daemon is not running. Start it with: clarvis start"}
    try:
        return client.call("memory_status")
    except Exception as e:
        return {"error": str(e)}


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
    client = ctx.fastmcp._lifespan_result["client"]
    if not client.is_daemon_running():
        return json.dumps({"error": "Clarvis daemon is not running. Start it with: clarvis start"})
    try:
        result = client.call("check_in")
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


# --- Sub-server factory ---

_TOOLS = [memory_add, memory_search, memory_cognify, memory_status, check_in]


def create_memory_server(daemon_client=None):
    """Create the memory MCP sub-server.

    Args:
        daemon_client: DaemonClient instance. If None, the parent server's
            lifespan client is used (tools access via ctx.fastmcp._lifespan_result).
            Pass a mock for testing.
    """
    from .core.ipc import DaemonClient

    # Memory operations (cognify, add on cold start) can take minutes.
    client = daemon_client if daemon_client is not None else DaemonClient(timeout=180.0)

    @asynccontextmanager
    async def memory_lifespan(server):
        yield {"client": client}

    srv = FastMCP("memory", lifespan=memory_lifespan)
    for fn in _TOOLS:
        srv.tool()(fn)
    return srv
