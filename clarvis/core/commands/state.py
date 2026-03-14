"""State queries, channels, and core utility command handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import CommandHandlers


# --- Context ---


def get_context(self: CommandHandlers, **kw) -> str:
    """Return ambient context: time, weather, location, now-playing."""
    from ..context_helpers import build_ambient_context

    return build_ambient_context(self.ctx.state, include_paused=True)


# --- Channels ---


def send_message(self: CommandHandlers, *, channel: str, chat_id: str, content: str, **kw) -> dict:
    """Send a message to a channel."""
    import asyncio

    mgr = self._get_service("channel_manager")
    if mgr is None:
        return {"error": "Channel manager not available"}
    ch = mgr.get_channel(channel)
    if ch is None:
        return {"error": f"Channel '{channel}' not found. Available: {mgr.enabled_channels}"}
    try:
        ok = asyncio.run_coroutine_threadsafe(mgr.send_message(channel, chat_id, content), self.ctx.loop).result(
            timeout=30
        )
        return {"sent": ok}
    except Exception as exc:
        return {"error": str(exc)}


COMMANDS: list[str] = [
    "get_context",
    "send_message",
]
