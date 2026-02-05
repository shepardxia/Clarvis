#!/usr/bin/env python3
"""Clarvis MCP Server - thin client that communicates with daemon."""

from mcp.server.fastmcp import FastMCP

from .core.ipc import get_daemon_client, DaemonClient
from .services import get_session_manager
from . import music_tools

mcp = FastMCP("clarvis")


def _get_client() -> DaemonClient:
    """Get daemon client, checking if daemon is running."""
    client = get_daemon_client()
    if not client.is_daemon_running():
        raise ConnectionError(
            "Clarvis daemon is not running. Start it with: "
            "uv run python -m clarvis.daemon"
        )
    return client


# --- Widget Tools ---

@mcp.tool()
async def ping() -> str:
    """Test that the server is running and daemon is connected."""
    try:
        client = _get_client()
        return client.call("ping")
    except ConnectionError as e:
        return str(e)


@mcp.tool()
async def get_weather() -> str:
    """Fetch current weather. Auto-detects location from IP if coordinates not provided."""
    try:
        client = _get_client()

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


@mcp.tool()
async def get_time(timezone: str = None) -> str:
    """Get current time. Auto-detects timezone if not provided."""
    try:
        client = _get_client()
        time_dict = client.call("refresh_time", timezone=timezone)

        from datetime import datetime
        dt = datetime.fromisoformat(time_dict['timestamp'])
        return f"{dt.strftime('%A, %B %d, %Y %H:%M')} ({time_dict['timezone']})"
    except ConnectionError as e:
        return str(e)
    except Exception as e:
        return f"Error getting time: {e}"


@mcp.tool()
async def get_token_usage() -> str:
    """Get Claude API token usage with 5-hour and 7-day limits."""
    import json
    try:
        client = _get_client()
        result = client.call("get_token_usage")
        return json.dumps(result, indent=2)
    except ConnectionError as e:
        return str(e)
    except Exception as e:
        return f"Error getting token usage: {e}"


# --- Thinking Feed Tools ---

@mcp.tool()
async def list_active_sessions() -> list[dict]:
    """List active Claude Code sessions with project name, status, and thought count."""
    manager = get_session_manager()
    return manager.list_active_sessions()


@mcp.tool()
async def get_session_thoughts(session_id: str, limit: int = 10) -> dict:
    """Get recent thinking blocks from a specific session."""
    manager = get_session_manager()
    result = manager.get_session_thoughts(session_id, limit)
    if result is None:
        return {"error": f"Session {session_id} not found"}
    return result


@mcp.tool()
async def get_latest_thought() -> dict:
    """Get the most recent thought across all sessions."""
    manager = get_session_manager()
    result = manager.get_latest_thought()
    if result is None:
        return {"message": "No active thoughts found"}
    return result


# --- Music Tools (Clautify) ---

music_tools.register(mcp)


def main():
    """Entry point for MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
