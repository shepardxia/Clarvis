"""Per-channel enabled chats — generalized from DiscordState.

Persists to ``~/.clarvis/channel_state.json``.  Changes take
effect immediately without daemon restart.

Schema::

    {
      "discord": {"enabled_chats": ["ch1", "ch2"]}
    }
"""

import logging
from pathlib import Path
from threading import RLock
from typing import Any

from ..core.paths import CLARVIS_HOME
from ..core.persistence import json_load_safe, json_save_atomic

logger = logging.getLogger(__name__)

_DEFAULT_PATH = CLARVIS_HOME / "channel_state.json"


class ChannelState:
    """Per-channel enabled chats. Replaces DiscordState."""

    def __init__(self, path: Path = _DEFAULT_PATH):
        self._path = path
        self._lock = RLock()
        self._data: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        """Load state from disk."""
        with self._lock:
            raw = json_load_safe(self._path)
            if isinstance(raw, dict):
                self._data = raw
            else:
                self._data = {}

    def _save(self) -> bool:
        """Persist state to disk atomically."""
        with self._lock:
            return json_save_atomic(self._path, self._data)

    def is_chat_enabled(self, channel: str, chat_id: str) -> bool:
        """Check if a chat is enabled on a channel."""
        with self._lock:
            ch_data = self._data.get(channel, {})
            return chat_id in ch_data.get("enabled_chats", [])

    def enable_chat(self, channel: str, chat_id: str) -> None:
        """Add a chat to the enabled list for a channel."""
        with self._lock:
            ch_data = self._data.setdefault(channel, {})
            chats = ch_data.setdefault("enabled_chats", [])
            if chat_id not in chats:
                chats.append(chat_id)
                self._save()

    def disable_chat(self, channel: str, chat_id: str) -> None:
        """Remove a chat from the enabled list for a channel."""
        with self._lock:
            ch_data = self._data.get(channel, {})
            chats = ch_data.get("enabled_chats", [])
            if chat_id in chats:
                chats.remove(chat_id)
                self._save()

    def enabled_chats(self, channel: str) -> list[str]:
        """Get list of enabled chat IDs for a channel."""
        with self._lock:
            ch_data = self._data.get(channel, {})
            return list(ch_data.get("enabled_chats", []))
