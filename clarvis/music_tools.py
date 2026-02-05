"""Music MCP tools (Clautify) — registered onto the shared FastMCP instance."""

import threading
from typing import Annotated, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .core.ipc import get_daemon_client

# Cached Clautify instance (thread-safe)
_player_instance = None
_player_lock = threading.Lock()


def _get_player():
    """Get cached Clautify instance for speed."""
    from clautify import Clautify

    global _player_instance
    with _player_lock:
        if _player_instance is None:
            _player_instance = Clautify()
        return _player_instance


def _get_client():
    """Get daemon client for context queries."""
    client = get_daemon_client()
    if not client.is_daemon_running():
        raise ConnectionError("Clarvis daemon is not running.")
    return client


# --- Context ---

async def get_music_context() -> str:
    """Get the user's music taste profile, current time, weather, and location.
    Call this before making music selection decisions to personalize choices."""
    import os
    from datetime import datetime

    sections = []

    try:
        client = _get_client()
        time_dict = client.call("refresh_time")
        dt = datetime.fromisoformat(time_dict['timestamp'])
        sections.append(f"## Current Time\n{dt.strftime('%A, %B %d, %Y %H:%M')} ({time_dict['timezone']})")
    except Exception:
        sections.append("## Current Time\nUnavailable")

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

    profile_path = os.path.expanduser("~/.claude/memories/music_profile_compact.md")
    try:
        with open(profile_path) as f:
            sections.append(f.read().strip())
    except FileNotFoundError:
        sections.append("## Music Profile\nNo profile found at ~/.claude/memories/music_profile_compact.md")

    return "\n\n".join(sections)


# --- Search & Play ---

async def search(
    query: Annotated[str, Field(description="What to search for")],
    category: Annotated[str, Field(description="'tracks', 'albums', 'artists', 'playlists', or 'all'")] = "tracks",
    limit: Annotated[int, Field(description="Max results to return")] = 10,
) -> list[dict]:
    """Search Spotify without playing. Results are stored server-side for later use
    with add_to_queue (reference items by their index number).
    Use search_and_play instead if you just want to play something."""
    try:
        return _get_player().search(query, category, limit)
    except Exception as e:
        return [{"error": str(e)}]


# --- Queue Management ---

async def add_to_queue(
    indices: Annotated[list[int], Field(description="Indices from the last search() results to queue, e.g. [0, 2, 3]")],
    play: Annotated[bool, Field(description="Start playing after adding")] = False,
    clear: Annotated[bool, Field(description="Clear queue before adding")] = False,
) -> dict:
    """Add items from the last search() results to the queue by index.
    Requires a prior search() call — indices reference those results.
    Use search_and_play instead for a single-step alternative."""
    try:
        return _get_player().queue(indices, play=play, clear=clear)
    except Exception as e:
        return {"error": str(e)}


async def play_album(
    index: Annotated[int, Field(description="Index of the album from the last search(category='albums') results")],
    start_at: Annotated[Optional[str], Field(description="Partial track title to start playing from")] = None,
    clear: Annotated[bool, Field(description="Clear queue before adding")] = True,
) -> dict:
    """Queue an entire album from the last search(category='albums') results and start playing.
    Requires a prior search(category='albums') call.
    Use search_and_play(category='albums') instead for a single-step alternative."""
    try:
        return _get_player().play_album(index, start_at=start_at, clear=clear)
    except Exception as e:
        return {"error": str(e)}


async def get_queue(
    limit: Annotated[int, Field(description="Max tracks to return")] = 20,
) -> list[dict]:
    """Get the current play queue contents (title, artist, album per track)."""
    try:
        return _get_player().get_queue(limit)
    except Exception as e:
        return [{"error": str(e)}]


async def clear_queue() -> dict:
    """Remove all tracks from the play queue."""
    try:
        return _get_player().clear_queue()
    except Exception as e:
        return {"error": str(e)}


# --- Playback Controls ---

async def now_playing() -> dict:
    """Get current playback state: track title, artist, album, position, duration, and
    whether the player is playing/paused/stopped."""
    try:
        return _get_player().now_playing()
    except Exception as e:
        return {"error": str(e)}


async def play() -> dict:
    """Resume playback (unpause)."""
    try:
        return _get_player().play()
    except Exception as e:
        return {"error": str(e)}


async def pause() -> dict:
    """Pause playback."""
    try:
        return _get_player().pause()
    except Exception as e:
        return {"error": str(e)}


async def skip(
    count: Annotated[int, Field(description="Number of tracks to skip forward")] = 1,
) -> dict:
    """Skip forward to the next track (or skip multiple)."""
    try:
        return _get_player().skip(count)
    except Exception as e:
        return {"error": str(e)}


async def previous() -> dict:
    """Go back to the previous track."""
    try:
        return _get_player().previous()
    except Exception as e:
        return {"error": str(e)}


# --- Volume ---

async def volume(
    level: Annotated[Optional[str], Field(description="Absolute '50', relative '+10' or '-5', or omit to get current")] = None,
) -> dict:
    """Get or set speaker volume. Supports absolute (0-100) and relative (+/- amount) levels.
    Omit level to get the current volume."""
    try:
        if level is not None:
            if level.lstrip("+-").isdigit() and not level.startswith(("+", "-")):
                return _get_player().volume(int(level))
            return _get_player().volume(level)
        return _get_player().volume(None)
    except Exception as e:
        return {"error": str(e)}


async def mute(
    state: Annotated[Optional[bool], Field(description="True to mute, False to unmute, omit to toggle")] = None,
) -> dict:
    """Mute, unmute, or toggle the speaker mute state."""
    try:
        return _get_player().mute(state)
    except Exception as e:
        return {"error": str(e)}


# --- Play Modes ---

async def shuffle(
    enabled: Annotated[Optional[bool], Field(description="True to enable, False to disable, omit to get current state")] = None,
) -> dict:
    """Get or set shuffle mode."""
    try:
        return _get_player().shuffle(enabled)
    except Exception as e:
        return {"error": str(e)}


async def repeat(
    mode: Annotated[Optional[str], Field(description="'off', 'all', or 'one'. Omit to get current mode")] = None,
) -> dict:
    """Get or set repeat mode."""
    try:
        return _get_player().repeat(mode)
    except Exception as e:
        return {"error": str(e)}


# --- Playlists ---

async def spotify_playlists(
    limit: Annotated[int, Field(description="Max playlists to return")] = 50,
) -> list[dict]:
    """Get the user's Spotify playlists (id and title)."""
    try:
        return _get_player().spotify_playlists(limit)
    except Exception as e:
        return [{"error": str(e)}]


async def spotify_playlist_tracks(
    playlist_id: Annotated[str, Field(description="Spotify playlist ID (e.g. 'spotify:playlist:37i9dQZF1DXcBWIGoYBM5M')")],
    limit: Annotated[int, Field(description="Max tracks to return")] = 100,
) -> list[dict]:
    """Get tracks from a specific Spotify playlist."""
    try:
        return _get_player().spotify_playlist_tracks(playlist_id, limit)
    except Exception as e:
        return [{"error": str(e)}]


async def sonos_playlists() -> list[dict]:
    """Get playlists saved on the Sonos system (id and title)."""
    try:
        return _get_player().sonos_playlists()
    except Exception as e:
        return [{"error": str(e)}]


# --- Registration ---

_TOOLS = [
    get_music_context,
    search_and_play,
    search,
    add_to_queue,
    play_album,
    get_queue,
    clear_queue,
    now_playing,
    play,
    pause,
    skip,
    previous,
    volume,
    mute,
    shuffle,
    repeat,
    spotify_playlists,
    spotify_playlist_tracks,
    sonos_playlists,
]


def register(mcp: FastMCP) -> None:
    """Register all music tools onto the given MCP server."""
    for fn in _TOOLS:
        mcp.tool()(fn)
