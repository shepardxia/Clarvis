#!/usr/bin/env python3
"""Clarvis MCP Server - thin client that communicates with daemon."""

from mcp.server.fastmcp import FastMCP

from .core.ipc import get_daemon_client, DaemonClient
from .services import get_session_manager

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


# --- Whimsy Verb Tools ---

@mcp.tool()
async def get_whimsy_verb(context: str = None) -> str:
    """
    Get a whimsical gerund verb describing Claude's current activity.

    Args:
        context: Optional thinking context. Uses latest thought if not provided.

    Returns:
        A whimsical gerund verb like "Pondering" or "Crafting"
    """
    try:
        client = _get_client()
        result = client.call("get_whimsy_verb", context=context)
        return result.get("verb") or "Thinking"
    except Exception as e:
        return f"Error: {e}"


# --- Vinyl Tools (Clautify) ---

# Cached Clautify instances by speaker name
_vinyl_instances: dict[str, "Clautify"] = {}


def _get_vinyl(speaker: str = None):
    """Get cached Clautify instance for speed."""
    from clautify import Clautify

    cache_key = speaker or "_default"
    if cache_key not in _vinyl_instances:
        _vinyl_instances[cache_key] = Clautify(speaker=speaker)
    return _vinyl_instances[cache_key]


def _clear_vinyl_cache():
    """Clear cached instances (e.g., if speakers change)."""
    global _vinyl_instances
    _vinyl_instances = {}


@mcp.tool()
async def search(query: str, category: str = "tracks", limit: int = 10) -> list[dict]:
    """
    Search Spotify for music. Results are stored for queueing by index.

    Args:
        query: Search query (artist, track, album name)
        category: One of 'tracks', 'albums', 'artists', 'playlists'
        limit: Max results to return (default: 10)

    Returns:
        List of results with index, id, title, artist, album, duration.
        Use the index with queue to add tracks to the queue.
    """
    try:
        vinyl = _get_vinyl()
        return vinyl.search(query, category, limit)
    except Exception as e:
        return [{"error": str(e)}]


@mcp.tool()
async def search_and_play(
    query: str,
    category: str = "tracks",
    index: int = 0,
    start_at: str = None,
    clear: bool = True,
    speaker: str = None
) -> dict:
    """
    Search and immediately play - combines search + queue in one call.

    This is the fastest way to play music. One call instead of search + queue.

    Args:
        query: Search query (artist, track, album name)
        category: "tracks" or "albums"
        index: Which result to play (default: 0 = first/best match)
        start_at: For albums, track to start at (partial title match)
        clear: Clear queue before adding (default: True)
        speaker: Speaker name (default: first found)

    Returns:
        Dict with search_results, queue, and now_playing
    """
    try:
        vinyl = _get_vinyl(speaker)
        return vinyl.search_and_play(query, category, index, start_at, clear)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def queue(
    indices: list[int],
    speaker: str = None,
    position: int = None,
    play: bool = False,
    clear: bool = False
) -> dict:
    """
    Add tracks to the Sonos queue by index from last search results.

    Args:
        indices: List of indices from the last search results (0-based)
        speaker: Speaker name (default: first found)
        position: Queue position to insert at (default: end)
        play: Start playback after queueing
        clear: Clear queue before adding

    Returns:
        Dict with queued count, queue_length, first_position, now_playing
    """
    try:
        vinyl = _get_vinyl(speaker)
        return vinyl.queue(indices, position=position, play=play, clear=clear)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def play_album(
    index: int,
    start_at: str = None,
    clear: bool = True,
    speaker: str = None
) -> dict:
    """
    Queue an album and start playing, optionally at a specific track.

    Args:
        index: Index of album from last search results
        start_at: Track to start at - partial track title to match (e.g. "野猿")
        clear: Clear queue before adding (default: True)
        speaker: Speaker name (default: first found)

    Returns:
        Dict with queue contents and now_playing
    """
    try:
        vinyl = _get_vinyl(speaker)
        return vinyl.play_album(index, start_at=start_at, clear=clear)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def now_playing(speaker: str = None) -> dict:
    """
    Get detailed current track info from Sonos.

    Args:
        speaker: Speaker name (default: first found)

    Returns:
        Dict with title, artist, album, position, duration, album_art_uri, state
    """
    try:
        vinyl = _get_vinyl(speaker)
        return vinyl.now_playing()
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def play(speaker: str = None) -> dict:
    """
    Start or resume playback.

    Args:
        speaker: Speaker name (default: first found)

    Returns:
        Dict with state and current track info
    """
    try:
        vinyl = _get_vinyl(speaker)
        return vinyl.play()
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def pause(speaker: str = None) -> dict:
    """
    Pause playback.

    Args:
        speaker: Speaker name (default: first found)

    Returns:
        Dict with state
    """
    try:
        vinyl = _get_vinyl(speaker)
        return vinyl.pause()
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def skip(speaker: str = None, count: int = 1) -> dict:
    """
    Skip to next track(s).

    Args:
        speaker: Speaker name (default: first found)
        count: Number of tracks to skip (default: 1)

    Returns:
        Dict with now_playing info
    """
    try:
        vinyl = _get_vinyl(speaker)
        return vinyl.skip(count)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def previous(speaker: str = None) -> dict:
    """
    Go to previous track.

    Args:
        speaker: Speaker name (default: first found)

    Returns:
        Dict with now_playing info
    """
    try:
        vinyl = _get_vinyl(speaker)
        return vinyl.previous()
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def volume(speaker: str = None, level: int = None) -> dict:
    """
    Get or set volume.

    Args:
        speaker: Speaker name (default: first found)
        level: Volume 0-100 (omit to get current)

    Returns:
        Dict with volume level
    """
    try:
        vinyl = _get_vinyl(speaker)
        return vinyl.volume(level)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def mute(speaker: str = None, mute: bool = None) -> dict:
    """
    Get or set mute state.

    Args:
        speaker: Speaker name (default: first found)
        mute: True to mute, False to unmute (omit to toggle)

    Returns:
        Dict with muted state
    """
    try:
        from clautify.speakers import get_coordinator
        coord = get_coordinator(speaker)
        if mute is None:
            # Toggle
            coord.mute = not coord.mute
        else:
            coord.mute = mute
        return {"muted": coord.mute, "speaker": coord.player_name}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def refresh_speakers() -> dict:
    """
    Re-discover Sonos speakers on the network.

    Use this if speakers have been added, removed, or changed while
    the daemon is running.

    Returns:
        Dict with list of discovered speaker names
    """
    try:
        from clautify.speakers import discover_speakers
        _clear_vinyl_cache()
        speakers = discover_speakers(force_refresh=True)
        return {"speakers": speakers, "refreshed": True}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def get_queue(speaker: str = None, limit: int = 20) -> list[dict]:
    """
    Get current queue contents.

    Args:
        speaker: Speaker name (default: first found)
        limit: Max items to return

    Returns:
        List of queued tracks with position, id, title, artist, album
    """
    try:
        vinyl = _get_vinyl(speaker)
        return vinyl.get_queue(limit)
    except Exception as e:
        return [{"error": str(e)}]


@mcp.tool()
async def clear_queue(speaker: str = None) -> dict:
    """
    Clear the queue.

    Args:
        speaker: Speaker name (default: first found)

    Returns:
        Dict with cleared status
    """
    try:
        vinyl = _get_vinyl(speaker)
        return vinyl.clear_queue()
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def shuffle(speaker: str = None, enabled: bool = None) -> dict:
    """
    Get or set shuffle mode.

    Args:
        speaker: Speaker name (default: first found)
        enabled: True/False to set, omit to get current

    Returns:
        Dict with shuffle state
    """
    try:
        vinyl = _get_vinyl(speaker)
        return vinyl.shuffle(enabled)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def repeat(speaker: str = None, mode: str = None) -> dict:
    """
    Get or set repeat mode.

    Args:
        speaker: Speaker name (default: first found)
        mode: 'off', 'all', or 'one' (omit to get current)

    Returns:
        Dict with repeat mode
    """
    try:
        vinyl = _get_vinyl(speaker)
        return vinyl.repeat(mode)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def spotify_playlists(limit: int = 50) -> list[dict]:
    """
    Get user's Spotify playlists.

    Args:
        limit: Max playlists to return

    Returns:
        List of playlists with id, name, track_count
    """
    try:
        vinyl = _get_vinyl()
        return vinyl.spotify_playlists(limit)
    except Exception as e:
        return [{"error": str(e)}]


@mcp.tool()
async def spotify_playlist_tracks(playlist_id: str, limit: int = 100) -> list[dict]:
    """
    Get tracks from a Spotify playlist.

    Args:
        playlist_id: Spotify playlist ID
        limit: Max tracks to return

    Returns:
        List of tracks with id, title, artist, album, duration_seconds
    """
    try:
        vinyl = _get_vinyl()
        return vinyl.spotify_playlist_tracks(playlist_id, limit)
    except Exception as e:
        return [{"error": str(e)}]


@mcp.tool()
async def sonos_playlists() -> list[dict]:
    """
    Get saved Sonos playlists.

    Returns:
        List of playlists with name and track_count
    """
    try:
        vinyl = _get_vinyl()
        return vinyl.sonos_playlists()
    except Exception as e:
        return [{"error": str(e)}]


@mcp.tool()
async def check_auth() -> dict:
    """
    Check Spotify authentication status.

    Returns:
        Dict with authenticated status. If not authenticated,
        includes auth_url and instructions.
    """
    try:
        vinyl = _get_vinyl()
        return vinyl.check_auth()
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def batch(operations: list[dict], speaker: str = None) -> list[dict]:
    """
    Execute multiple vinyl operations in one call for speed.

    Each operation is a dict with 'op' key and operation-specific params.

    Args:
        operations: List of operations, e.g.:
            [
                {"op": "search", "query": "jazz", "category": "tracks"},
                {"op": "queue", "indices": [0, 1], "play": True},
                {"op": "volume", "level": 50}
            ]
        speaker: Speaker name (default: first found)

    Supported operations:
        - search: query, category, limit
        - search_and_play: query, category, index, start_at, clear
        - queue: indices, position, play, clear
        - play_album: index, start_at, clear
        - play, pause, stop, skip, previous
        - volume: level
        - shuffle: enabled
        - repeat: mode
        - now_playing
        - clear_queue
        - jump_to: index

    Returns:
        List of results, one per operation
    """
    try:
        vinyl = _get_vinyl(speaker)
        results = []

        for op_dict in operations:
            op = op_dict.get("op", "")
            try:
                if op == "search":
                    r = vinyl.search(op_dict.get("query", ""), op_dict.get("category", "tracks"), op_dict.get("limit", 10))
                elif op == "search_and_play":
                    r = vinyl.search_and_play(op_dict.get("query", ""), op_dict.get("category", "tracks"),
                                               op_dict.get("index", 0), op_dict.get("start_at"), op_dict.get("clear", True))
                elif op == "queue":
                    r = vinyl.queue(op_dict.get("indices", []), op_dict.get("position"), op_dict.get("play", False), op_dict.get("clear", False))
                elif op == "play_album":
                    r = vinyl.play_album(op_dict.get("index", 0), op_dict.get("start_at"), op_dict.get("clear", True))
                elif op == "play":
                    r = vinyl.play()
                elif op == "pause":
                    r = vinyl.pause()
                elif op == "stop":
                    r = vinyl.stop()
                elif op == "skip":
                    r = vinyl.skip(op_dict.get("count", 1))
                elif op == "previous":
                    r = vinyl.previous()
                elif op == "volume":
                    r = vinyl.volume(op_dict.get("level"))
                elif op == "shuffle":
                    r = vinyl.shuffle(op_dict.get("enabled"))
                elif op == "repeat":
                    r = vinyl.repeat(op_dict.get("mode"))
                elif op == "now_playing":
                    r = vinyl.now_playing()
                elif op == "clear_queue":
                    r = vinyl.clear_queue()
                elif op == "jump_to":
                    r = vinyl.jump_to(op_dict.get("index", 0))
                else:
                    r = {"error": f"Unknown operation: {op}"}
                results.append({"op": op, "result": r})
            except Exception as e:
                results.append({"op": op, "error": str(e)})

        return results
    except Exception as e:
        return [{"error": str(e)}]


def main():
    """Entry point for MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
