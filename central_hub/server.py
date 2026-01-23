#!/usr/bin/env python3
"""Central Hub MCP Server - exposes tools for widget data sources."""

from mcp.server.fastmcp import FastMCP

from .core import get_hub_section, DEFAULT_TIMEZONE
from .daemon import refresh_location, refresh_weather, refresh_time
from .services import get_controller, get_session_manager

mcp = FastMCP("central-hub")


# --- Widget Tools ---

@mcp.tool()
async def ping() -> str:
    """Test that the server is running."""
    return "pong"


@mcp.tool()
async def get_weather(latitude: float = None, longitude: float = None) -> str:
    """
    Fetch current weather for a location and write to widget file.

    Args:
        latitude: Latitude (default: auto-detect from IP)
        longitude: Longitude (default: auto-detect from IP)

    Returns:
        Weather summary string
    """
    try:
        # Check cache first (only for auto-detected location)
        if latitude is None and longitude is None:
            cached = get_hub_section("weather")
            if cached:
                return (
                    f"{cached['temperature']}°F, {cached['description']}, "
                    f"Wind: {cached['wind_speed']} mph ({cached.get('city', '')}) [cached]"
                )

        # Call daemon to refresh weather
        weather_dict = refresh_weather(latitude, longitude)
        city = weather_dict.get('city', 'Unknown')

        return (
            f"{weather_dict['temperature']}°F, {weather_dict['description']}, "
            f"Wind: {weather_dict['wind_speed']} mph ({city})"
        )

    except Exception as e:
        return f"Error fetching weather: {e}"


@mcp.tool()
async def get_time(timezone: str = DEFAULT_TIMEZONE) -> str:
    """
    Get current time and write to widget file.

    Args:
        timezone: Timezone name (default: America/Los_Angeles)

    Returns:
        Current time string
    """
    try:
        # Call daemon to refresh time
        time_dict = refresh_time(timezone)
        
        # Format display string
        from datetime import datetime
        dt = datetime.fromisoformat(time_dict['timestamp'])
        return f"{dt.strftime('%A, %B %d, %Y %H:%M')} ({time_dict['timezone']})"

    except Exception as e:
        return f"Error getting time: {e}"


@mcp.tool()
async def get_claude_status() -> str:
    """
    Read current Claude status from the hub data file.

    Returns:
        Current status information
    """
    try:
        from .core import read_hub_data
        hub_data = read_hub_data()
        status_data = hub_data.get("status", {})
        
        if not status_data:
            return "No status data found"
        
        status = status_data.get("status", "unknown")
        color = status_data.get("color", "gray")
        context_percent = status_data.get("context_percent", 0)

        return f"Status: {status}, Color: {color}, Context: {context_percent:.1f}%"

    except Exception as e:
        return f"Error reading status: {e}"


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
