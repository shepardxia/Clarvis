#!/usr/bin/env python3
"""Clarvis MCP Server — embedded in the daemon, served over SSE.

Uses FastMCP 2.x composition: main server (daemon tools) + mounted sub-servers.
Tool handlers access daemon state and services directly (no IPC).
"""

import asyncio

from fastmcp import Context, FastMCP

from ..core.context_helpers import (
    location_summary,
    now_playing_summary,
    time_summary,
    weather_summary,
)
from ._helpers import get_daemon, make_lifespan
from .channel_tools import create_channel_server
from .memory_tools import create_memory_server
from .spotify_tools import create_spotify_server
from .timer_tools import create_timer_server

# --- Tool implementations ---


async def ping(ctx: Context = None) -> str:
    """Pongs."""
    get_daemon(ctx)
    return "pong"


async def get_context(ctx: Context = None) -> str:
    """Get current time, weather, location, and currently playing music."""
    d = get_daemon(ctx)
    parts = []
    loop = asyncio.get_running_loop()

    # Weather (refresh if stale)
    try:
        weather = d.state.get("weather")
        if not weather or not weather.get("temperature"):
            weather = await loop.run_in_executor(None, d.refresh.refresh_weather)
        ws = weather_summary(weather)
        if ws:
            parts.append(ws)
    except Exception:
        pass

    loc = location_summary(d.state.get("location"))
    if loc:
        parts.append(loc)

    # Time (always refresh for accuracy)
    try:
        time_dict = await loop.run_in_executor(None, d.refresh.refresh_time)
        ts = time_summary(time_dict, fmt="full")
        parts.append(ts or "time: unavailable")
    except Exception:
        parts.append("time: unavailable")

    # Currently playing on Spotify
    def _get_session():
        from .spotify_tools import _default_get_session

        return _default_get_session()

    np = await loop.run_in_executor(None, now_playing_summary, _get_session)
    if np:
        parts.append(np)

    return "\n".join(parts)


# Voice pipeline signal
async def prompt_response(ctx: Context = None) -> str:
    """Ask a follow-up question and wait for the user's spoken reply."""
    d = get_daemon(ctx)
    if d.bus is None:
        return "Voice pipeline not available."
    d.bus.emit("voice:prompt_reply")
    return "Listening."


# --- Tool lists ---

_TOOLS = [
    ping,
    get_context,
    prompt_response,
]

# --- Per-port tool configs ---
# Each key controls a tool group; True = enabled, False = disabled,
# dict = enabled with constraints (e.g. memory visibility).

STANDARD_TOOLS = {
    "spotify": False,
    "timers": False,
    "channels": True,
    "prompt_response": False,
    "memory": False,
}

HOME_TOOLS = {
    "spotify": True,
    "timers": True,
    "channels": True,
    "prompt_response": True,
    "memory": True,
}

CHANNEL_DEFAULTS = {
    "spotify": False,
    "timers": False,
    "channels": True,
    "prompt_response": False,
    "memory": {"visibility": "all"},
}


# --- App factory ---


def create_app(daemon, tool_config, get_session=None):
    """Create the Clarvis MCP server.

    Args:
        daemon: CentralHubDaemon instance (or mock with .state, .refresh, etc.).
        tool_config: Dict controlling which tool groups are enabled.
            Keys: ``spotify``, ``timers``, ``channels``, ``memory``,
            ``prompt_response``.
            Values: ``True`` (enabled), ``False`` (disabled), or
            ``{key: value}`` (enabled with constraints).
            Use STANDARD_TOOLS, HOME_TOOLS, or CHANNEL_DEFAULTS.
        get_session: Callable returning SpotifySession instance. Passed through
            to spotify sub-server. Pass a mock factory for testing.
    """

    def _enabled(key: str) -> bool:
        v = tool_config.get(key, True)
        return bool(v)

    app = FastMCP("clarvis", lifespan=make_lifespan(daemon))

    # Core tools — filter prompt_response if disabled
    for fn in _TOOLS:
        if fn is prompt_response and not _enabled("prompt_response"):
            continue
        app.tool()(fn)

    # Sub-servers
    if _enabled("spotify"):
        app.mount(create_spotify_server(get_session=get_session))
    if _enabled("timers"):
        app.mount(create_timer_server(daemon))
    if _enabled("channels") and getattr(daemon, "channel_manager", None) is not None:
        app.mount(create_channel_server(daemon))

    # Memory — single path, driven entirely by tool_config
    if daemon.memory_service is not None:
        mem_cfg = tool_config.get("memory", False)
        if mem_cfg:
            visibility = "master"
            if isinstance(mem_cfg, dict) and "visibility" in mem_cfg:
                visibility = mem_cfg["visibility"]
            app.mount(create_memory_server(daemon, visibility=visibility))

    return app


# --- Embedded server ---


async def run_embedded(
    daemon,
    host="127.0.0.1",
    port=7777,
    memory_port=7778,
    channel_ports=None,
    voice_tools_override=None,
    ready: asyncio.Event | None = None,
):
    """Run MCP servers embedded in daemon's event loop.

    Port 7777: standard tools (ping, context, spotify, timers).
    Port 7778: standard + memory + voice tools (for ~/.clarvis/home/ sessions).
    Additional channel ports: one per unique tool_config across channels.

    Args:
        channel_ports: list of ``(tool_config, port)`` tuples.  Each gets
            its own uvicorn server with a restricted tool surface.
        voice_tools_override: dict of tool overrides from config.json voice.tools,
            applied on top of STANDARD_TOOLS and HOME_TOOLS defaults.
        ready: if provided, set after all servers have bound their ports.
    """
    import socket

    import uvicorn

    standard_cfg = {**STANDARD_TOOLS, **(voice_tools_override or {})}
    home_cfg = {**HOME_TOOLS, **(voice_tools_override or {})}

    main_app = create_app(daemon, tool_config=standard_cfg)
    mem_app = create_app(daemon, tool_config=home_cfg)

    entries: list[tuple[uvicorn.Server, socket.socket]] = []

    def _bind(asgi_app, bind_port: int) -> tuple[uvicorn.Server, socket.socket]:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, bind_port))
        sock.set_inheritable(True)
        cfg = uvicorn.Config(asgi_app, host=host, port=bind_port, log_level="warning")
        return uvicorn.Server(cfg), sock

    main_asgi = main_app.http_app(transport="streamable-http")
    mem_asgi = mem_app.http_app(transport="streamable-http")

    entries.append(_bind(main_asgi, port))
    entries.append(_bind(mem_asgi, memory_port))

    for tool_cfg, ch_port in channel_ports or []:
        ch_app = create_app(daemon, tool_config=tool_cfg)
        ch_asgi = ch_app.http_app(transport="streamable-http")
        entries.append(_bind(ch_asgi, ch_port))

    # Phase 1: load config and start each server (binds + listens)
    for srv, sock in entries:
        if not srv.config.loaded:
            srv.config.load()
        srv.lifespan = srv.config.lifespan_class(srv.config)
        await srv.startup(sockets=[sock])

    if ready is not None:
        ready.set()

    # Phase 2: serve until shutdown
    try:
        await asyncio.gather(*(srv.main_loop() for srv, _ in entries))
    finally:
        for srv, sock in entries:
            await srv.shutdown(sockets=[sock])
            sock.close()
