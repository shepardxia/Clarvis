#!/usr/bin/env python3
"""Central Hub MCP Server - thin client that communicates with daemon."""

from mcp.server.fastmcp import FastMCP

from .core.ipc import get_daemon_client, DaemonClient
from .services import get_controller, get_session_manager

mcp = FastMCP("central-hub")


def _get_client() -> DaemonClient:
    """Get daemon client, checking if daemon is running."""
    client = get_daemon_client()
    if not client.is_daemon_running():
        raise ConnectionError(
            "Clarvis daemon is not running. Start it with: "
            "uv run python -m central_hub.daemon"
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
async def get_weather(latitude: float = None, longitude: float = None) -> str:
    """
    Fetch current weather for a location.

    Args:
        latitude: Latitude (default: auto-detect from IP)
        longitude: Longitude (default: auto-detect from IP)

    Returns:
        Weather summary string
    """
    try:
        client = _get_client()

        # If coordinates provided, refresh with them
        if latitude is not None and longitude is not None:
            weather = client.call("refresh_weather", latitude=latitude, longitude=longitude)
        else:
            # Try cached first, then refresh if needed
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
    """
    Get current time.

    Args:
        timezone: Timezone name (default: auto-detect)

    Returns:
        Current time string
    """
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
async def get_claude_status() -> str:
    """
    Read current Claude status from the daemon.

    Returns:
        Current status information
    """
    try:
        client = _get_client()
        status = client.call("get_status")

        if not status:
            return "No status data found"

        return (
            f"Status: {status.get('status', 'unknown')}, "
            f"Color: {status.get('color', 'gray')}, "
            f"Context: {status.get('context_percent', 0):.1f}%"
        )
    except ConnectionError as e:
        return str(e)
    except Exception as e:
        return f"Error reading status: {e}"


@mcp.tool()
async def get_token_usage() -> str:
    """Get current Claude API token usage.

    Returns 5-hour and 7-day usage limits with utilization percentages and reset times.
    """
    import json
    try:
        client = _get_client()
        result = client.call("get_token_usage")
        return json.dumps(result, indent=2)
    except ConnectionError as e:
        return str(e)
    except Exception as e:
        return f"Error getting token usage: {e}"


@mcp.tool()
async def get_clarvis_state() -> dict:
    """
    Get Clarvis's full current state including displayed session, status, weather, and full history.

    Returns:
        Dictionary with Clarvis's complete state including all tracked session histories
    """
    try:
        client = _get_client()
        return client.call("get_state")
    except ConnectionError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def list_clarvis_sessions() -> list[dict]:
    """
    List all sessions Clarvis is tracking with their current state.

    Returns:
        List of tracked sessions with status and context history
    """
    try:
        client = _get_client()
        sessions = client.call("get_sessions")
        return sessions if sessions else [{"message": "No sessions tracked"}]
    except ConnectionError as e:
        return [{"error": str(e)}]
    except Exception as e:
        return [{"error": str(e)}]


@mcp.tool()
async def get_clarvis_session(session_id: str) -> dict:
    """
    Get detailed information about a specific tracked session.

    Args:
        session_id: The session ID to look up

    Returns:
        Session details including full history
    """
    try:
        client = _get_client()
        return client.call("get_session", session_id=session_id)
    except ConnectionError as e:
        return {"error": str(e)}
    except RuntimeError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}


# --- Thinking Feed Tools ---

@mcp.tool()
async def list_active_sessions() -> list[dict]:
    """
    List all active Claude Code sessions across all projects.

    Returns list of sessions with metadata including project name,
    status (active/idle/ended), and thought count.
    """
    manager = get_session_manager()
    return manager.list_active_sessions()


@mcp.tool()
async def get_session_thoughts(session_id: str, limit: int = 10) -> dict:
    """
    Get recent thinking blocks from a specific session.

    Args:
        session_id: UUID of the session
        limit: Maximum number of thoughts to return (default: 10)

    Returns:
        Session info with list of recent thoughts, or error if not found
    """
    manager = get_session_manager()
    result = manager.get_session_thoughts(session_id, limit)
    if result is None:
        return {"error": f"Session {session_id} not found"}
    return result


@mcp.tool()
async def get_latest_thought() -> dict:
    """
    Get the single most recent thought across all sessions.

    Returns:
        Latest thought with session context, or empty dict if none
    """
    manager = get_session_manager()
    result = manager.get_latest_thought()
    if result is None:
        return {"message": "No active thoughts found"}
    return result


# --- Sonos Tools ---

@mcp.tool()
async def sonos_discover() -> list[str]:
    """
    Discover all Sonos speakers on the network.

    Returns:
        List of speaker names
    """
    controller = get_controller()
    names = controller.discover()
    return names if names else ["No Sonos speakers found"]


@mcp.tool()
async def sonos_now_playing(speaker: str = None) -> dict:
    """
    Get current track info from a Sonos speaker.

    Args:
        speaker: Speaker name (default: first found)

    Returns:
        Track info (title, artist, album, position, duration)
    """
    return get_controller().now_playing(speaker)


@mcp.tool()
async def sonos_play(speaker: str = None) -> str:
    """
    Start playback on a Sonos speaker.

    Args:
        speaker: Speaker name (default: first found)
    """
    return get_controller().play(speaker)


@mcp.tool()
async def sonos_pause(speaker: str = None) -> str:
    """
    Pause playback on a Sonos speaker.

    Args:
        speaker: Speaker name (default: first found)
    """
    return get_controller().pause(speaker)


@mcp.tool()
async def sonos_next(speaker: str = None) -> str:
    """
    Skip to next track on a Sonos speaker.

    Args:
        speaker: Speaker name (default: first found)
    """
    return get_controller().next_track(speaker)


@mcp.tool()
async def sonos_previous(speaker: str = None) -> str:
    """
    Go to previous track on a Sonos speaker.

    Args:
        speaker: Speaker name (default: first found)
    """
    return get_controller().previous_track(speaker)


@mcp.tool()
async def sonos_volume(speaker: str = None, level: int = None) -> str:
    """
    Get or set volume on a Sonos speaker.

    Args:
        speaker: Speaker name (default: first found)
        level: Volume level 0-100 (omit to get current)

    Returns:
        Current or new volume level
    """
    return get_controller().volume(speaker, level)


@mcp.tool()
async def sonos_mute(speaker: str = None, mute: bool = None) -> str:
    """
    Get or set mute state on a Sonos speaker.

    Args:
        speaker: Speaker name (default: first found)
        mute: True to mute, False to unmute (omit to toggle)
    """
    return get_controller().mute(speaker, mute)


def main():
    """Entry point for MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
