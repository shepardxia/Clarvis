"""Timer MCP sub-server — mounted onto the main Clarvis server.

Exposes timer management tools (set, cancel, list) that use the
daemon's TimerService directly (in-process).
"""

from typing import Annotated

from fastmcp import Context
from pydantic import Field

from ..services.timer_service import parse_duration
from ._helpers import create_tool_server, get_daemon_service


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


async def set_timer(
    name: Annotated[
        str,
        Field(description="Unique timer name"),
    ],
    duration: Annotated[
        str,
        Field(description="Duration: '5m', '1h30m', '90s', or seconds as number"),
    ],
    label: str = "",
    recurring: bool = False,
    wake_clarvis: Annotated[
        bool,
        Field(description="Also wake up Clarvis when the timer fires"),
    ] = False,
    ctx: Context = None,
) -> str:
    """Set a named timer. Overwrites any existing timer with the same name."""
    svc, err = get_daemon_service(ctx, "timer_service", "Timer service")
    if err:
        return err
    try:
        seconds = parse_duration(duration)
    except ValueError as e:
        return f"Error: {e}"
    svc.set_timer(name, seconds, recurring, label, wake_clarvis)
    suffix = " [+clarvis]" if wake_clarvis else ""
    return f"Timer '{name}' set for {_fmt_duration(seconds)}{suffix}"


async def cancel_timer(
    name: Annotated[
        str,
        Field(description="Timer name to cancel"),
    ],
    ctx: Context = None,
) -> str:
    """Cancel an active timer."""
    svc, err = get_daemon_service(ctx, "timer_service", "Timer service")
    if err:
        return err
    if svc.cancel(name):
        return f"Cancelled '{name}'"
    return f"No timer '{name}' found"


async def list_timers(
    ctx: Context = None,
) -> str:
    """List all active timers with remaining time."""
    svc, err = get_daemon_service(ctx, "timer_service", "Timer service")
    if err:
        return err
    timers = svc.list_timers()
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
        if t.get("wake_clarvis"):
            parts.append("[+clarvis]")
        lines.append(" ".join(parts))
    return "\n".join(lines)


# --- Sub-server factory ---

_TOOLS = [set_timer, cancel_timer, list_timers]


def create_timer_server(daemon):
    """Create the timer MCP sub-server."""
    return create_tool_server("timer", _TOOLS, daemon)
