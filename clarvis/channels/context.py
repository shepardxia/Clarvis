"""Context enrichment for inbound messages.

Builds a human-readable prefix from metadata + registry lookup,
prepended to the message content before sending to the agent.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .events import InboundMessage
    from .registry import UserRegistry


def _fmt_size(n: int) -> str:
    """Format byte count as human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}" if unit != "B" else f"{n}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def build_context_prefix(msg: "InboundMessage", registry: "UserRegistry") -> str:
    """Build a conditional context prefix from metadata + registry.

    Only includes fields with actual data. Returns empty string if
    no enrichment is available.
    """
    ts = msg.timestamp.strftime("%Y-%m-%d %H:%M %Z")
    parts: list[str] = [f"[{msg.channel} {ts}]"]
    meta = msg.metadata or {}

    # User identity (from registry lookup)
    user = registry.get_by_channel_id(msg.channel, msg.sender_id)
    if user:
        username = meta.get("author_username", "unknown")
        name_str = "|".join(user["names"]) if user.get("names") else ""
        aff_str = "|".join(user["affiliations"]) if user.get("affiliations") else ""
        identity = username
        extras = ", ".join(filter(None, [name_str, aff_str]))
        if extras:
            identity += f" ({extras})"
        parts.append(identity)

    # Reply context
    ref_content = meta.get("referenced_message_content")
    ref_author = meta.get("referenced_message_author")
    if ref_content:
        reply = f'replying to {ref_author or "unknown"}: "{ref_content[:200]}"'
        parts.append(reply)

    # Mentions (filter out bot's own username)
    mentions = meta.get("mentions") or []
    bot_username = meta.get("bot_username")
    mentions = [m for m in mentions if m != bot_username]
    if mentions:
        parts.append(f"mentions: {', '.join(mentions)}")

    # Attachments
    attachments = meta.get("attachment_info") or []
    if attachments:
        att_strs = []
        for a in attachments:
            s = a["filename"]
            if a.get("content_type"):
                s += f" ({a['content_type']}"
                if a.get("size"):
                    s += f", {_fmt_size(a['size'])}"
                s += ")"
            att_strs.append(s)
        parts.append(f"attached: {', '.join(att_strs)}")

    return " | ".join(parts) + "\n"
