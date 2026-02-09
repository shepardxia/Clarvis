#!/usr/bin/env python3
"""Clarvis MCP Server — embedded in the daemon, served over SSE.

Uses FastMCP 2.x composition: main server (daemon tools) + mounted sub-servers.
Tool handlers access daemon state and services directly (no IPC).
"""

import json
from contextlib import asynccontextmanager
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Optional

from fastmcp import Context, FastMCP
from pydantic import Field

from .memory_tools import create_memory_server
from .services import get_session_manager
from .spotify_tools import create_spotify_server

if TYPE_CHECKING:
    from .daemon import CentralHubDaemon

# --- Helpers ---


def _daemon(ctx: Context) -> "CentralHubDaemon":
    return ctx.fastmcp._lifespan_result["daemon"]


# --- Tool implementations ---


async def ping(ctx: Context = None) -> str:
    """Health check."""
    _daemon(ctx)
    return "pong"


async def get_weather(ctx: Context = None) -> str:
    """Fetch current weather. Auto-detects location from IP if coordinates not provided."""
    try:
        d = _daemon(ctx)
        weather = d.state.get("weather")
        if not weather or not weather.get("temperature"):
            weather = d.refresh.refresh_weather()
        return (
            f"{weather.get('temperature', '?')}°F, {weather.get('description', 'unknown')}, "
            f"Wind: {weather.get('wind_speed', 0)} mph ({weather.get('city', 'Unknown')})"
        )
    except Exception as e:
        return f"Error fetching weather: {e}"


async def get_time(
    timezone: Annotated[Optional[str], Field(description="Timezone name, or omit to auto-detect")] = None,
    ctx: Context = None,
) -> str:
    """Get current time. Auto-detects timezone if not provided."""
    try:
        d = _daemon(ctx)
        time_dict = d.refresh.refresh_time(timezone)
        dt = datetime.fromisoformat(time_dict["timestamp"])
        return f"{dt.strftime('%A, %B %d, %Y %H:%M')} ({time_dict['timezone']})"
    except Exception as e:
        return f"Error getting time: {e}"


async def get_token_usage(ctx: Context = None) -> str:
    """Get Claude API token usage with 5-hour and 7-day limits."""
    try:
        d = _daemon(ctx)
        if not d.token_usage_service:
            return json.dumps({"error": "Token usage service not initialized", "is_stale": True})
        result = d.token_usage_service.get_usage()
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error getting token usage: {e}"


async def get_context(ctx: Context = None) -> str:
    """Get current time, weather, and location."""
    d = _daemon(ctx)
    parts = []

    try:
        time_dict = d.refresh.refresh_time()
        dt = datetime.fromisoformat(time_dict["timestamp"])
        parts.append(f"{dt.strftime('%A, %B %d, %Y %H:%M')} ({time_dict['timezone']})")
    except Exception:
        parts.append("Time: unavailable")

    try:
        weather = d.state.get("weather")
        if not weather or not weather.get("temperature"):
            weather = d.refresh.refresh_weather()
        if weather and weather.get("temperature"):
            parts.append(
                f"{weather.get('city', 'Unknown')}: "
                f"{weather.get('temperature', '?')}°F, "
                f"{weather.get('description', 'unknown')}, "
                f"Wind: {weather.get('wind_speed', 0)} mph"
            )
    except Exception:
        pass

    return " | ".join(parts)


# -- Thinking Feed Tools (no daemon needed, self-contained) --


async def list_active_sessions() -> list[dict]:
    """List active Claude Code sessions with project name, status, and thought count."""
    manager = get_session_manager()
    return manager.list_active_sessions()


async def get_session_thoughts(session_id: str, limit: int = 10) -> dict:
    """Get recent thinking blocks from a specific session."""
    manager = get_session_manager()
    result = manager.get_session_thoughts(session_id, limit)
    if result is None:
        return {"error": f"Session {session_id} not found"}
    return result


async def get_latest_thought() -> dict:
    """Get the most recent thought across all sessions."""
    manager = get_session_manager()
    result = manager.get_latest_thought()
    if result is None:
        return {"message": "No active thoughts found"}
    return result


# Voice pipeline signal
async def continue_listening() -> str:
    """Ask a question and wait for the user's spoken reply."""
    return "Listening."


# --- Tool lists ---

_TOOLS = [
    ping,
    get_context,
    continue_listening,
]


# --- App factory ---


def create_app(daemon, get_session=None):
    """Create the Clarvis MCP server.

    Args:
        daemon: CentralHubDaemon instance (or mock with .state, .refresh, etc.).
        get_session: Callable returning SpotifySession instance. Passed through
            to spotify sub-server. Pass a mock factory for testing.
    """

    @asynccontextmanager
    async def daemon_lifespan(server):
        yield {"daemon": daemon}

    app = FastMCP("clarvis", lifespan=daemon_lifespan)

    for fn in _TOOLS:
        app.tool()(fn)

    app.mount(create_spotify_server(get_session=get_session))
    app.mount(create_memory_server(daemon))

    return app


# --- Embedded server ---


async def run_embedded(daemon, host="127.0.0.1", port=7777):
    """Run MCP server embedded in daemon's event loop via streamable HTTP.

    Uses uvicorn to serve the FastMCP Starlette app. Intended to be
    launched as an asyncio task from daemon.run().
    """
    import uvicorn

    app = create_app(daemon)
    asgi = app.http_app(transport="streamable-http")
    config = uvicorn.Config(asgi, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()
