#!/usr/bin/env python3
"""Clarvis MCP Server — embedded in the daemon, served over SSE.

Uses FastMCP 2.x. Only port 7777 remains — serves external Claude Code sessions.
Agent tools (memory, spotify, timers) are daemon IPC commands via ctools.
"""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastmcp import Context, FastMCP
from pydantic import Field

from ..core.context_helpers import build_ambient_context, now_playing_summary

# --- Lifespan helpers (inlined from deleted _helpers.py) ---


def get_daemon(ctx):
    """Extract daemon from FastMCP lifespan context."""
    return ctx.fastmcp._lifespan_result["daemon"]


def make_lifespan(daemon, **extras):
    @asynccontextmanager
    async def lifespan(server):
        yield {"daemon": daemon, **extras}

    return lifespan


# --- Tool implementations ---


async def ping(ctx: Context = None) -> str:
    """Pongs."""
    get_daemon(ctx)
    return "pong"


async def get_context(ctx: Context = None) -> str:
    """Get current time, weather, location, and currently playing music."""
    d = get_daemon(ctx)
    loop = asyncio.get_running_loop()

    # Refresh stale weather
    try:
        weather = d.state.get("weather")
        if not weather or not weather.get("temperature"):
            await loop.run_in_executor(None, d.refresh.refresh_weather)
    except Exception:
        pass

    # Refresh time for accuracy
    time_state = None
    try:
        time_state = await loop.run_in_executor(None, d.refresh.refresh_time)
    except Exception:
        pass

    # Currently playing on Spotify
    def _get_session():
        from ..services.spotify_session import get_spotify_session

        return get_spotify_session()

    np = await loop.run_in_executor(None, now_playing_summary, _get_session)

    parts = build_ambient_context(d.state.get, now_playing=np, time_state=time_state)
    return "\n".join(parts)


async def stage_memory(
    summary: Annotated[
        str,
        Field(description="Session summary to queue for Clarvis's next reflect cycle."),
    ],
    ctx: Context = None,
) -> str:
    """Stage a session summary for memory processing.

    Called by /remember from Claude Code sessions. The summary is queued
    and processed by Clarvis during the next reflect cycle.
    """
    from datetime import datetime, timezone

    from ..core.persistence import json_load_safe, json_save_atomic

    daemon = get_daemon(ctx)
    queue_file = Path(daemon.staging_dir) / "remember_queue.json"
    items = json_load_safe(queue_file) or []

    items.append(
        {
            "summary": summary,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
    json_save_atomic(queue_file, items)
    return f"Queued for reflect ({len(items)} item{'s' if len(items) != 1 else ''} pending)."


# --- Tool list ---

_TOOLS = [
    ping,
    get_context,
    stage_memory,
]

# --- Per-port tool config (only standard remains) ---

STANDARD_TOOLS = {
    "spotify": False,
    "timers": False,
    "channels": True,
    "prompt_response": False,
    "memory": False,
}


# --- App factory ---


def create_app(daemon, tool_config=None):
    """Create the Clarvis MCP server (standard tools only)."""
    app = FastMCP("clarvis", lifespan=make_lifespan(daemon))
    for fn in _TOOLS:
        app.tool()(fn)
    return app


# --- Embedded server ---


async def run_embedded(
    daemon,
    host="127.0.0.1",
    port=7777,
    ready: asyncio.Event | None = None,
):
    """Run MCP server embedded in daemon's event loop.

    Port 7777: standard tools (ping, context, stage_memory).
    """
    import socket

    import uvicorn

    app = create_app(daemon, tool_config=STANDARD_TOOLS)
    asgi = app.http_app(transport="streamable-http")

    config = uvicorn.Config(asgi, host=host, port=port, log_level="warning")
    srv = uvicorn.Server(config)
    config.load()
    srv.lifespan = config.lifespan_class(config)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.setblocking(False)

    await srv.startup(sockets=[sock])
    if ready:
        ready.set()

    try:
        await srv.main_loop()
    finally:
        await srv.shutdown(sockets=[sock])
        sock.close()
