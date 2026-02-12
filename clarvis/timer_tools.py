"""Timer MCP sub-server — mounted onto the main Clarvis server.

Exposes timer management tools (set, cancel, list) that use the
daemon's TimerService directly (in-process).
"""

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Annotated

from fastmcp import Context, FastMCP
from pydantic import Field

from .services.timer_service import parse_duration

if TYPE_CHECKING:
    from .daemon import CentralHubDaemon


def _daemon(ctx: Context) -> "CentralHubDaemon":
    return ctx.fastmcp._lifespan_result["daemon"]


def _fmt_duration(seconds: float) -> str:
    """Format seconds as human-readable: '1h 30m 15s'."""
    seconds = int(seconds)
    parts = []
    if seconds >= 3600:
        parts.append(f"{seconds // 3600}h")
        seconds %= 3600
    if seconds >= 60:
        parts.append(f"{seconds // 60}m")
        seconds %= 60
    if seconds > 0 or not parts:
        parts.append(f"{seconds}s")
    return " ".join(parts)


# --- Tool implementations ---


_VALID_TRIGGERS = {"simple", "voice"}


async def set_timer(
    name: Annotated[
        str,
        Field(description="Unique timer name (e.g. 'pasta', 'meeting')"),
    ],
    duration: Annotated[
        str,
        Field(description="Duration: '5m', '1h30m', '90s', or seconds as number"),
    ],
    label: Annotated[
        str,
        Field(description="What this timer is for"),
    ] = "",
    recurring: Annotated[
        bool,
        Field(description="Repeat after each firing"),
    ] = False,
    trigger: Annotated[
        str,
        Field(description="Notification when timer fires: 'simple' (flash + sound) or 'voice' (wake voice assistant)"),
    ] = "simple",
    ctx: Context = None,
) -> str:
    """Set a named timer. Overwrites any existing timer with the same name."""
    d = _daemon(ctx)
    if not d.timer_service:
        return "Error: Timer service not available"
    if trigger not in _VALID_TRIGGERS:
        return f"Error: Invalid trigger '{trigger}'. Must be one of: {', '.join(sorted(_VALID_TRIGGERS))}"
    try:
        seconds = parse_duration(duration)
    except ValueError as e:
        return f"Error: {e}"
    d.timer_service.set_timer(name, seconds, recurring, label, trigger)
    return f"Timer '{name}' set for {_fmt_duration(seconds)} [{trigger}]"


async def cancel_timer(
    name: Annotated[
        str,
        Field(description="Timer name to cancel"),
    ],
    ctx: Context = None,
) -> str:
    """Cancel an active timer."""
    d = _daemon(ctx)
    if not d.timer_service:
        return "Error: Timer service not available"
    if d.timer_service.cancel(name):
        return f"Cancelled '{name}'"
    return f"No timer '{name}' found"


async def list_timers(
    ctx: Context = None,
) -> str:
    """List all active timers with remaining time."""
    d = _daemon(ctx)
    if not d.timer_service:
        return "Error: Timer service not available"
    timers = d.timer_service.list_timers()
    if not timers:
        return "No active timers."
    lines = []
    for t in timers:
        remaining = _fmt_duration(t["remaining"])
        parts = [t["name"]]
        if t.get("label"):
            parts.append(f"({t['label']})")
        parts.append(f"-- {remaining} remaining")
        if t.get("recurring"):
            parts.append("[recurring]")
        if t.get("trigger", "simple") != "simple":
            parts.append(f"[{t['trigger']}]")
        lines.append(" ".join(parts))
    return "\n".join(lines)


# --- Sub-server factory ---

_TOOLS = [set_timer, cancel_timer, list_timers]


def create_timer_server(daemon):
    """Create the timer MCP sub-server.

    Args:
        daemon: CentralHubDaemon instance (or mock with .timer_service).
            Injected into lifespan for tool access.
    """

    @asynccontextmanager
    async def timer_lifespan(server):
        yield {"daemon": daemon}

    srv = FastMCP("timer", lifespan=timer_lifespan)
    for fn in _TOOLS:
        srv.tool()(fn)
    return srv
