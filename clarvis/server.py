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
async def get_claude_status() -> str:
    """Get current Claude status (status, color, context percent)."""
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


@mcp.tool()
async def get_clarvis_state() -> dict:
    """Get full Clarvis state: displayed session, status, weather, and all history."""
    try:
        client = _get_client()
        return client.call("get_state")
    except ConnectionError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def list_clarvis_sessions() -> list[dict]:
    """List all tracked sessions with status and context history."""
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
    """Get detailed info for a specific tracked session including full history."""
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


# --- Whimsy Verb Tools ---

@mcp.tool()
async def get_whimsy_verb(context: str = None) -> str:
    """Get a whimsical gerund verb (e.g., "Pondering") for Claude's activity."""
    try:
        client = _get_client()
        result = client.call("get_whimsy_verb", context=context)
        return result.get("verb") or "Thinking"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
async def get_music_context() -> str:
    """Get music context including user taste profile, current time, weather, and location.

    IMPORTANT: Always call this before making music selection decisions.
    Returns the user's music preferences and current context to inform choices.
    """
    import os
    from datetime import datetime

    sections = []

    # Time context
    try:
        client = _get_client()
        time_dict = client.call("refresh_time")
        dt = datetime.fromisoformat(time_dict['timestamp'])
        sections.append(f"## Current Time\n{dt.strftime('%A, %B %d, %Y %H:%M')} ({time_dict['timezone']})")
    except Exception:
        sections.append("## Current Time\nUnavailable")

    # Weather + location context
    try:
        client = _get_client()
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

    # Music taste profile
    profile_path = os.path.expanduser("~/.claude/memories/music_profile_compact.md")
    try:
        with open(profile_path) as f:
            sections.append(f.read().strip())
    except FileNotFoundError:
        sections.append("## Music Profile\nNo profile found at ~/.claude/memories/music_profile_compact.md")

    return "\n\n".join(sections)


# --- Music Tools (Clautify) ---

import threading

# Cached Clautify instance (thread-safe)
_player_instance: "Clautify | None" = None
_player_lock = threading.Lock()


def _get_player():
    """Get cached Clautify instance for speed."""
    from clautify import Clautify

    global _player_instance
    with _player_lock:
        if _player_instance is None:
            _player_instance = Clautify()
        return _player_instance


@mcp.tool()
async def search(query: str, category: str = "tracks", limit: int = 10) -> list[dict]:
    """Search Spotify. Results stored for queueing by index."""
    try:
        player = _get_player()
        return player.search(query, category, limit)
    except Exception as e:
        return [{"error": str(e)}]


@mcp.tool()
async def search_and_play(
    query: str,
    category: str = "tracks",
    index: int = 0,
    start_at: str = None,
    clear: bool = True,
) -> dict:
    """Search and immediately play - combines search + queue in one call."""
    try:
        player = _get_player()
        return player.search_and_play(query, category, index, start_at, clear)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def queue(
    indices: list[int],
    position: int = None,
    play: bool = False,
    clear: bool = False
) -> dict:
    """Add tracks to Sonos queue by index from last search results."""
    try:
        player = _get_player()
        return player.queue(indices, position=position, play=play, clear=clear)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def play_album(
    index: int,
    start_at: str = None,
    clear: bool = True,
) -> dict:
    """Queue album from search results and start playing."""
    try:
        player = _get_player()
        return player.play_album(index, start_at=start_at, clear=clear)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def now_playing() -> dict:
    """Get current track info (title, artist, album, position, state)."""
    try:
        player = _get_player()
        return player.now_playing()
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def play() -> dict:
    """Start or resume playback."""
    try:
        player = _get_player()
        return player.play()
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def pause() -> dict:
    """Pause playback."""
    try:
        player = _get_player()
        return player.pause()
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def skip(count: int = 1) -> dict:
    """Skip to next track(s)."""
    try:
        player = _get_player()
        return player.skip(count)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def previous() -> dict:
    """Go to previous track."""
    try:
        player = _get_player()
        return player.previous()
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def volume(level: int = None) -> dict:
    """Get or set volume (0-100). Omit level to get current."""
    try:
        player = _get_player()
        return player.volume(level)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def mute(mute: bool = None) -> dict:
    """Get, set, or toggle mute state."""
    try:
        player = _get_player()
        return player.mute(mute)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def refresh_speakers() -> dict:
    """Re-discover Sonos speakers on the network."""
    try:
        from clautify.speakers import discover_speakers, clear_speaker_cache
        clear_speaker_cache()
        speakers = discover_speakers(force_refresh=True)
        return {"speakers": speakers, "refreshed": True}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def get_queue(limit: int = 20) -> list[dict]:
    """Get current Sonos queue contents."""
    try:
        player = _get_player()
        return player.get_queue(limit)
    except Exception as e:
        return [{"error": str(e)}]


@mcp.tool()
async def clear_queue() -> dict:
    """Clear the Sonos queue."""
    try:
        player = _get_player()
        return player.clear_queue()
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def shuffle(enabled: bool = None) -> dict:
    """Get or set shuffle mode."""
    try:
        player = _get_player()
        return player.shuffle(enabled)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def repeat(mode: str = None) -> dict:
    """Get or set repeat mode ('off', 'all', 'one')."""
    try:
        player = _get_player()
        return player.repeat(mode)
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def spotify_playlists(limit: int = 50) -> list[dict]:
    """Get user's Spotify playlists."""
    try:
        player = _get_player()
        return player.spotify_playlists(limit)
    except Exception as e:
        return [{"error": str(e)}]


@mcp.tool()
async def spotify_playlist_tracks(playlist_id: str, limit: int = 100) -> list[dict]:
    """Get tracks from a Spotify playlist."""
    try:
        player = _get_player()
        return player.spotify_playlist_tracks(playlist_id, limit)
    except Exception as e:
        return [{"error": str(e)}]


@mcp.tool()
async def sonos_playlists() -> list[dict]:
    """Get saved Sonos playlists."""
    try:
        player = _get_player()
        return player.sonos_playlists()
    except Exception as e:
        return [{"error": str(e)}]


@mcp.tool()
async def check_auth() -> dict:
    """Check Spotify authentication status."""
    try:
        player = _get_player()
        return player.check_auth()
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def batch(operations: list[dict]) -> list[dict]:
    """Execute multiple operations in one call (search, queue, play, volume, etc.)."""
    try:
        player = _get_player()
        results = []

        for op_dict in operations:
            op = op_dict.get("op", "")
            try:
                if op == "search":
                    r = player.search(op_dict.get("query", ""), op_dict.get("category", "tracks"), op_dict.get("limit", 10))
                elif op == "search_and_play":
                    r = player.search_and_play(op_dict.get("query", ""), op_dict.get("category", "tracks"),
                                               op_dict.get("index", 0), op_dict.get("start_at"), op_dict.get("clear", True))
                elif op == "queue":
                    r = player.queue(op_dict.get("indices", []), op_dict.get("position"), op_dict.get("play", False), op_dict.get("clear", False))
                elif op == "play_album":
                    r = player.play_album(op_dict.get("index", 0), op_dict.get("start_at"), op_dict.get("clear", True))
                elif op == "play":
                    r = player.play()
                elif op == "pause":
                    r = player.pause()
                elif op == "stop":
                    r = player.stop()
                elif op == "skip":
                    r = player.skip(op_dict.get("count", 1))
                elif op == "previous":
                    r = player.previous()
                elif op == "volume":
                    r = player.volume(op_dict.get("level"))
                elif op == "shuffle":
                    r = player.shuffle(op_dict.get("enabled"))
                elif op == "repeat":
                    r = player.repeat(op_dict.get("mode"))
                elif op == "now_playing":
                    r = player.now_playing()
                elif op == "clear_queue":
                    r = player.clear_queue()
                elif op == "jump_to":
                    r = player.jump_to(op_dict.get("index", 0))
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
