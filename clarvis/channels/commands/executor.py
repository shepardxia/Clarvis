"""Command executor — dispatches parsed command dicts to handlers.

Follows clautify's executor pattern: table-driven dispatch via
``getattr(self, f"_cmd_{command}")``.

Cross-channel: works on any channel, uses ChannelState for
enable/disable and UserRegistry for registration.
"""

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..registry import UserRegistry
    from ..state import ChannelState

logger = logging.getLogger(__name__)


class CommandExecutor:
    """Execute bot commands against registry and channel state."""

    def __init__(self, registry: "UserRegistry", state: "ChannelState"):
        self._registry = registry
        self._state = state

    def execute(self, cmd: dict[str, Any], sender_id: str, chat_id: str, channel: str) -> str:
        """Dispatch a parsed command dict and return a response string."""
        command = cmd["command"]
        handler = getattr(self, f"_cmd_{command}", None)
        if not handler:
            return f"Unknown command: {command}"
        try:
            return handler(cmd, sender_id, chat_id, channel)
        except Exception:
            logger.exception("Command execution failed: %s", cmd)
            return "Command failed — check daemon logs."

    def _cmd_register(self, cmd: dict[str, Any], sender_id: str, chat_id: str, channel: str) -> str:
        username = cmd["username"]
        new_names = cmd.get("name", [])
        new_orgs = cmd.get("org", [])

        # Validate orgs against predefined list
        if new_orgs:
            invalid = [o for o in new_orgs if not self._registry.is_valid_org(o)]
            if invalid:
                valid = self._registry.orgs
                return (
                    f"Unknown org(s): {', '.join(invalid)}\n"
                    f"Valid orgs: {', '.join(valid) if valid else '(none defined)'}"
                )

        # Additive merge with existing profile
        existing = self._registry.get_by_channel_id(channel, sender_id)
        if existing:
            old_names = existing.get("names", [])
            old_orgs = existing.get("affiliations", [])
            merged_names = list(dict.fromkeys(old_names + new_names))
            merged_orgs = list(dict.fromkeys(old_orgs + new_orgs))
        else:
            merged_names = new_names
            merged_orgs = new_orgs

        self._registry.register(
            username=username,
            names=merged_names or None,
            affiliations=merged_orgs or None,
            channel=channel,
            channel_user_id=sender_id,
        )

        parts = [f"Registered **{username}**"]
        if merged_names:
            parts.append(f"({', '.join(merged_names)})")
        if merged_orgs:
            parts.append(f"[{', '.join(merged_orgs)}]")
        return " ".join(parts)

    def _cmd_unregister(self, cmd: dict[str, Any], sender_id: str, chat_id: str, channel: str) -> str:
        removed = self._registry.unregister(channel, sender_id)
        if removed:
            return f"Unregistered **{removed}**"
        return "You are not registered."

    def _cmd_enable(self, cmd: dict[str, Any], sender_id: str, chat_id: str, channel: str) -> str:
        self._state.enable_chat(channel, chat_id)
        return f"Chat `{chat_id}` enabled on {channel}."

    def _cmd_disable(self, cmd: dict[str, Any], sender_id: str, chat_id: str, channel: str) -> str:
        self._state.disable_chat(channel, chat_id)
        return f"Chat `{chat_id}` disabled on {channel}."

    def _cmd_status(self, cmd: dict[str, Any], sender_id: str, chat_id: str, channel: str) -> str:
        lines: list[str] = []

        # Users
        users = self._registry.users
        if users:
            lines.append(f"**Registered users** ({len(users)}):")
            for username, profile in users.items():
                parts = [f"  - {username}"]
                names = profile.get("names")
                if names:
                    parts.append(f"({', '.join(names)})")
                orgs = profile.get("affiliations")
                if orgs:
                    parts.append(f"— {', '.join(orgs)}")
                lines.append(" ".join(parts))
        else:
            lines.append("No registered users.")

        lines.append("")

        # Orgs
        orgs = self._registry.orgs
        if orgs:
            lines.append(f"**Orgs** ({len(orgs)}): {', '.join(orgs)}")
        else:
            lines.append("No orgs defined.")

        lines.append("")

        # Enabled chats on current channel
        chats = self._state.enabled_chats(channel)
        if chats:
            lines.append(f"**Enabled chats** on {channel} ({len(chats)}):")
            for ch in chats:
                marker = " (this)" if ch == chat_id else ""
                lines.append(f"  - `{ch}`{marker}")
        else:
            lines.append(f"No enabled chats on {channel}.")

        return "\n".join(lines)
