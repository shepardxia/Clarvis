"""Spotify DSL MCP sub-server — mounted onto the main Clarvis server.

Single tool that accepts DSL command strings via the clautify package.
"""

import time
from typing import Annotated

from contextlib import asynccontextmanager

from fastmcp import FastMCP, Context
from pydantic import Field


# --- Default session factory (lazy init) ---

_session_cache = {}


def _default_get_session():
    """Lazy SpotifySession singleton. No lock needed — asyncio is single-threaded for sync calls."""
    if "instance" not in _session_cache:
        from clautify.dsl import SpotifySession
        _session_cache["instance"] = SpotifySession.from_config(eager=False)
    return _session_cache["instance"]


# --- Device cache ---

_device_cache = {"names": None, "ts": 0}
_DEVICE_TTL = 300  # 5 minutes


def _ensure_devices(session):
    """Fetch and cache device names. Called on first tool invocation and periodically."""
    now = time.time()
    if _device_cache["names"] is not None and now - _device_cache["ts"] < _DEVICE_TTL:
        return
    try:
        result = session.run("get devices")
        data = result.get("data")
        if data and hasattr(data, "devices"):
            _device_cache["names"] = [d.name for d in data.devices.values()]
        elif isinstance(data, list):
            _device_cache["names"] = [d.get("name", str(d)) for d in data]
        _device_cache["ts"] = now
    except Exception:
        pass


# --- Tool ---

async def spotify(
    command: Annotated[str, Field(
        description='Command string, e.g. \'play "jazz" volume 70 mode shuffle on "Den"\''
    )],
    ctx: Context = None,
) -> dict:
    """Execute a Spotify command using natural command strings.

    Quoted strings are auto-resolved (searched and played) — no need to search first.
    Modifiers compose in a single call. Examples:

        play "Bohemian Rhapsody"
        play "jazz" volume 70 mode shuffle on "Den"
        search "radiohead" artists limit 5
        now playing
        queue "Stairway to Heaven"
        skip 3
        volume 50
        get devices

    ACTIONS: play "query", pause, resume, skip [N], seek <ms>,
    queue "query", like/unlike <URI>, follow/unfollow <URI>,
    save/unsave <URI>, add <URI> to <URI>, remove <URI> from <URI>,
    create playlist "name", delete playlist <URI>.

    QUERIES: search "query" [tracks|artists|albums|playlists],
    now playing, get queue, get devices,
    library [tracks|artists], info <URI>, history,
    recommend N for <playlist-URI>.

    COMPOSABLE MODIFIERS (chain onto actions, or use standalone):
    volume N (0-100), mode shuffle|repeat|normal, on "device name".
    Query-only modifiers: limit N, offset N.

    TARGETS: Spotify URIs (spotify:track:abc) or quoted strings.

    Every response includes an "available_devices" list with device names
    you can use with the on modifier.

    Returns {"status": "ok", ..., "available_devices": [...]} on success,
    {"error": "...", "available_devices": [...]} on failure.
    """
    session = ctx.fastmcp._lifespan_result["get_session"]()
    _ensure_devices(session)

    try:
        result = session.run(command)
    except Exception as e:
        result = {"error": str(e)}

    if _device_cache["names"] is not None:
        result["available_devices"] = _device_cache["names"]

    return result


# --- Sub-server factory ---

_TOOLS = [spotify]


def create_spotify_server(get_session=None):
    """Create the Spotify DSL MCP sub-server.

    Args:
        get_session: Callable returning a SpotifySession instance. Defaults to
            lazy singleton via from_config(). Pass a mock factory for testing.
    """
    factory = get_session or _default_get_session

    @asynccontextmanager
    async def session_lifespan(server):
        yield {"get_session": factory}

    srv = FastMCP("spotify", lifespan=session_lifespan)
    for fn in _TOOLS:
        srv.tool()(fn)
    return srv
