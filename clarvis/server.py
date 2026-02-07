#!/usr/bin/env python3
"""Clarvis MCP Server — thin client that communicates with daemon.

Uses FastMCP 2.x composition: main server (daemon tools) + mounted music sub-server.
Dependencies injected via lifespan context for testability.
"""

import json
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Optional

from fastmcp import Context, FastMCP
from pydantic import Field

from .core.ipc import DaemonClient, get_daemon_client
from .services import get_session_manager
from .spotify_tools import create_spotify_server

# --- Tool implementations (module-level, registered by create_app) ---


# Helper to get daemon client from context, with connectivity check.
def _client(ctx: Context) -> DaemonClient:
    client = ctx.fastmcp._lifespan_result["client"]
    if not client.is_daemon_running():
        raise ConnectionError("Clarvis daemon is not running. Start it with: clarvis start")
    return client


# -- Widget Tools --


async def ping(ctx: Context = None) -> str:
    """Test that the server is running and daemon is connected."""
    try:
        return _client(ctx).call("ping")
    except ConnectionError as e:
        return str(e)


async def get_weather(ctx: Context = None) -> str:
    """Fetch current weather. Auto-detects location from IP if coordinates not provided."""
    try:
        client = _client(ctx)
        weather = client.call("get_weather")
        if not weather or not weather.get("temperature"):
            weather = client.call("refresh_weather")
        return (
            f"{weather.get('temperature', '?')}°F, {weather.get('description', 'unknown')}, "
            f"Wind: {weather.get('wind_speed', 0)} mph ({weather.get('city', 'Unknown')})"
        )
    except ConnectionError as e:
        return str(e)
    except Exception as e:
        return f"Error fetching weather: {e}"


async def get_time(
    timezone: Annotated[Optional[str], Field(description="Timezone name, or omit to auto-detect")] = None,
    ctx: Context = None,
) -> str:
    """Get current time. Auto-detects timezone if not provided."""
    try:
        client = _client(ctx)
        time_dict = client.call("refresh_time", timezone=timezone)
        dt = datetime.fromisoformat(time_dict["timestamp"])
        return f"{dt.strftime('%A, %B %d, %Y %H:%M')} ({time_dict['timezone']})"
    except ConnectionError as e:
        return str(e)
    except Exception as e:
        return f"Error getting time: {e}"


async def get_token_usage(ctx: Context = None) -> str:
    """Get Claude API token usage with 5-hour and 7-day limits."""
    try:
        result = _client(ctx).call("get_token_usage")
        return json.dumps(result, indent=2)
    except ConnectionError as e:
        return str(e)
    except Exception as e:
        return f"Error getting token usage: {e}"


async def get_music_context(ctx: Context = None) -> str:
    """Get the user's music taste profile, current time, weather, and location.
    Call this before making music selection decisions to personalize choices."""
    sections = []

    try:
        client = _client(ctx)
        time_dict = client.call("refresh_time")
        dt = datetime.fromisoformat(time_dict["timestamp"])
        sections.append(f"## Current Time\n{dt.strftime('%A, %B %d, %Y %H:%M')} ({time_dict['timezone']})")
    except Exception:
        sections.append("## Current Time\nUnavailable")

    try:
        client = _client(ctx)
        weather = client.call("get_weather") or client.call("refresh_weather")
        if weather and weather.get("temperature"):
            sections.append(
                f"## Weather & Location\n"
                f"{weather.get('city', 'Unknown')}: "
                f"{weather.get('temperature', '?')}°F, "
                f"{weather.get('description', 'unknown')}, "
                f"Wind: {weather.get('wind_speed', 0)} mph"
            )
    except Exception:
        pass

    profile_path = os.path.expanduser("~/.claude/memories/music_profile_compact.md")
    try:
        with open(profile_path) as f:
            sections.append(f.read().strip())
    except FileNotFoundError:
        sections.append("## Music Profile\nNo profile found at ~/.claude/memories/music_profile_compact.md")

    return "\n\n".join(sections)


# -- Thinking Feed Tools (no daemon client needed) --


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


# --- Tool lists ---

# Tools that need daemon client (get ctx injected)
_DAEMON_TOOLS = [
    ping,
    get_weather,
    get_time,
    get_token_usage,
    get_music_context,
]

# Tools that are self-contained (no ctx needed)
_SESSION_TOOLS = [
    list_active_sessions,
    get_session_thoughts,
    get_latest_thought,
]


# --- App factory ---


def create_app(daemon_client=None, get_session=None):
    """Create the Clarvis MCP server.

    Args:
        daemon_client: DaemonClient instance. Defaults to global singleton.
            Pass a mock for testing.
        get_session: Callable returning SpotifySession instance. Passed through
            to spotify sub-server. Pass a mock factory for testing.
    """
    client = daemon_client if daemon_client is not None else get_daemon_client()

    @asynccontextmanager
    async def daemon_lifespan(server):
        yield {"client": client}

    app = FastMCP("clarvis", lifespan=daemon_lifespan)

    for fn in _DAEMON_TOOLS + _SESSION_TOOLS:
        app.tool()(fn)

    app.mount(create_spotify_server(get_session=get_session))

    return app


# Production instance
mcp = create_app()


def main():
    """Entry point for MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
