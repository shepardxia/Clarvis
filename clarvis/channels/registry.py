"""Global user registry — persistent identity store for cross-channel users.

Stores user profiles with names, affiliations, and per-channel IDs in
``~/.clarvis/registry.json``.  Thread-safe with auto-save on mutation.
"""

import copy
import logging
from pathlib import Path
from threading import RLock
from typing import Any

from ..core.paths import CLARVIS_HOME
from ..core.persistence import json_load_safe, json_save_atomic

logger = logging.getLogger(__name__)

_DEFAULT_PATH = CLARVIS_HOME / "registry.json"


class UserRegistry:
    """Thread-safe persistent user registry.

    Schema (``~/.clarvis/registry.json``)::

        {
          "users": {
            "shepardxia": {
              "names": ["Shepard", "Shep"],
              "affiliations": ["CS Lab"],
              "channels": {
                "discord": {"user_id": "650197363591348250"}
              }
            }
          }
        }
    """

    def __init__(self, path: Path = _DEFAULT_PATH, admin_user_ids: list[str] | None = None):
        self._path = path
        self._lock = RLock()
        self._data: dict[str, Any] = {"users": {}}
        self._admin_user_ids: set[str] = set(admin_user_ids or [])
        # Reverse index: (channel, user_id) → username for O(1) lookup
        self._channel_index: dict[tuple[str, str], str] = {}
        self.load()
        self._migrate_roles()

    def load(self) -> None:
        """Load registry from disk."""
        with self._lock:
            raw = json_load_safe(self._path)
            if isinstance(raw, dict) and "users" in raw:
                self._data = raw
            else:
                self._data = {"users": {}}
            self._rebuild_index()

    def save(self) -> bool:
        """Persist registry to disk atomically."""
        with self._lock:
            return json_save_atomic(self._path, self._data)

    def _rebuild_index(self) -> None:
        """Rebuild reverse index from data. Caller must hold lock."""
        idx: dict[tuple[str, str], str] = {}
        for username, profile in self._data.get("users", {}).items():
            for channel, ch_info in profile.get("channels", {}).items():
                uid = ch_info.get("user_id")
                if uid:
                    idx[(channel, uid)] = username
        self._channel_index = idx

    @property
    def orgs(self) -> list[str]:
        """Predefined org names (seeded in registry.json)."""
        with self._lock:
            return list(self._data.get("orgs", []))

    def is_valid_org(self, name: str) -> bool:
        """Check if an org name is in the predefined list (case-insensitive)."""
        lower = name.lower()
        return any(o.lower() == lower for o in self.orgs)

    def add_org(self, name: str) -> bool:
        """Add an org to the predefined list. Returns False if already present."""
        with self._lock:
            orgs = self._data.setdefault("orgs", [])
            if any(o.lower() == name.lower() for o in orgs):
                return False
            orgs.append(name)
            self.save()
            return True

    def remove_org(self, name: str) -> bool:
        """Remove an org from the predefined list (case-insensitive). Returns False if not found."""
        with self._lock:
            orgs = self._data.get("orgs", [])
            lower = name.lower()
            for i, o in enumerate(orgs):
                if o.lower() == lower:
                    orgs.pop(i)
                    self.save()
                    return True
            return False

    @property
    def users(self) -> dict[str, dict]:
        with self._lock:
            return copy.deepcopy(self._data.get("users", {}))

    def get_by_channel_id(self, channel: str, user_id: str) -> dict | None:
        """Look up a user by their channel-specific ID.

        Returns the full user dict (names, affiliations, channels) or None.
        Uses reverse index for O(1) lookup.
        """
        with self._lock:
            username = self._channel_index.get((channel, user_id))
            if username is None:
                return None
            profile = self._data.get("users", {}).get(username)
            return dict(profile) if profile else None

    def get_by_name(self, name: str) -> dict | None:
        """Look up a user by username key or any name in their names list.

        Case-insensitive matching.  The returned dict includes a
        ``_username`` key with the registry username.
        """
        lower = name.lower()
        with self._lock:
            for username, profile in self._data.get("users", {}).items():
                if username.lower() == lower:
                    return {**profile, "_username": username}
                for n in profile.get("names", []):
                    if n.lower() == lower:
                        return {**profile, "_username": username}
        return None

    def register(
        self,
        username: str,
        names: list[str] | None = None,
        affiliations: list[str] | None = None,
        channel: str | None = None,
        channel_user_id: str | None = None,
    ) -> None:
        """Add or update a user in the registry.

        Merges into existing profile if username already exists.
        """
        with self._lock:
            users = self._data.setdefault("users", {})
            profile = users.setdefault(username, {})
            if names is not None:
                profile["names"] = names
            if affiliations is not None:
                profile["affiliations"] = affiliations
            if channel and channel_user_id:
                channels = profile.setdefault("channels", {})
                channels[channel] = {"user_id": channel_user_id}
                self._channel_index[(channel, channel_user_id)] = username
            if "role" not in profile:
                profile["role"] = self._role_for(profile)
            self.save()

    def unregister(self, channel: str, user_id: str) -> str | None:
        """Remove a user by their channel-specific ID.

        Removes the channel entry.  If no channels remain, removes the
        entire user.  Returns the removed username, or None if not found.
        """
        with self._lock:
            username = self._channel_index.pop((channel, user_id), None)
            if username is None:
                return None
            profile = self._data.get("users", {}).get(username)
            if profile is None:
                return None
            profile.get("channels", {}).pop(channel, None)
            if not profile.get("channels"):
                self._data["users"].pop(username, None)
            self.save()
            return username

    def is_registered(self, channel: str, user_id: str) -> bool:
        """Check if a user is registered for the given channel."""
        return self.get_by_channel_id(channel, user_id) is not None

    def all_name_mappings(self, channel: str) -> dict[str, str]:
        """Return ``{name: channel_user_id}`` for all users on a channel.

        Maps both the username key and all names in the names list to the
        channel user ID.  Used for @mention replacement in outbound messages.
        """
        mappings: dict[str, str] = {}
        with self._lock:
            for username, profile in self._data.get("users", {}).items():
                ch_info = profile.get("channels", {}).get(channel, {})
                uid = ch_info.get("user_id")
                if not uid:
                    continue
                mappings[username] = uid
                for name in profile.get("names", []):
                    mappings[name] = uid
        return mappings

    def _migrate_roles(self) -> None:
        """Assign roles to existing users that lack one. Saves once if any changed."""
        changed = False
        with self._lock:
            for _username, profile in self._data.get("users", {}).items():
                if "role" in profile:
                    continue
                profile["role"] = self._role_for(profile)
                changed = True
            if changed:
                self.save()

    def _role_for(self, profile: dict) -> str:
        """Determine role based on whether any channel user_id is in admin set."""
        for ch_info in profile.get("channels", {}).values():
            if ch_info.get("user_id") in self._admin_user_ids:
                return "admin"
        return "user"

    def get_role(self, channel: str, user_id: str) -> str | None:
        """Look up a user's role by channel identity. Returns None if not registered."""
        with self._lock:
            username = self._channel_index.get((channel, user_id))
            if username is None:
                return None
            profile = self._data.get("users", {}).get(username)
            return profile.get("role", "user") if profile else None

    def set_role(self, username: str, role: str) -> bool:
        """Set role by username. Returns False if user not found."""
        lower = username.lower()
        with self._lock:
            for uname, profile in self._data.get("users", {}).items():
                if uname.lower() == lower:
                    profile["role"] = role
                    self.save()
                    return True
        return False
