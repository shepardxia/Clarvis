"""Channel MCP sub-server — mounted onto the main Clarvis server.

Exposes channel management tools (send message, list channels) that
use the daemon's ChannelManager directly (in-process).
"""

from typing import Annotated

from fastmcp import Context
from pydantic import Field

from ._helpers import create_tool_server, get_daemon_service

# --- Tool implementations ---


async def send_message(
    channel: Annotated[
        str,
        Field(description="Channel name to send to (e.g. 'telegram', 'discord', 'voice')"),
    ],
    chat_id: Annotated[
        str,
        Field(description="Chat/conversation identifier on the target channel"),
    ],
    content: Annotated[
        str,
        Field(description="Message content to send"),
    ],
    ctx: Context = None,
) -> str:
    """Send a message to any enabled channel."""
    mgr, err = get_daemon_service(ctx, "channel_manager", "Channel manager")
    if err:
        return err

    ch = mgr.get_channel(channel)
    if ch is None:
        available = mgr.enabled_channels
        return f"Error: Channel '{channel}' not found. Available: {', '.join(available)}"

    ok = await mgr.send_message(channel, chat_id, content)
    if ok:
        return f"Sent to {channel}/{chat_id}"
    return f"Error: Failed to send to {channel}/{chat_id}"


async def get_channels(
    ctx: Context = None,
) -> str:
    """List enabled channels and status."""
    mgr, err = get_daemon_service(ctx, "channel_manager", "Channel manager")
    if err:
        return err

    status = mgr.get_status()
    if not status:
        return "No channels configured."

    lines = []
    for name, info in status.items():
        state = "running" if info.get("running") else "stopped"
        lines.append(f"{name}: {state}")
    return "\n".join(lines)


# --- Sub-server factory ---

_TOOLS = [send_message, get_channels]


def create_channel_server(daemon):
    """Create the channel MCP sub-server."""
    return create_tool_server("channels", _TOOLS, daemon)
