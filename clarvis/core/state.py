"""Single source of truth for all Clarvis state."""

import copy
import logging
import threading

logger = logging.getLogger(__name__)


class StateStore:
    """Central state store.

    All state changes go through this class.
    """

    def __init__(self):
        self._state: dict[str, dict] = {
            "status": {},
            "sessions": {},
            "weather": {},
            "location": {},
            "time": {},
            "voice_text": {},
            "mic": {},
        }
        self._lock = threading.RLock()  # Reentrant for nested calls
        self._status_locked = False
        self._pre_lock_status: dict | None = None

    @property
    def status_locked(self) -> bool:
        """Whether status updates are currently locked by the voice pipeline."""
        return self._status_locked

    def lock_status(self) -> None:
        """Lock status updates — external writes to 'status' are ignored.

        Saves the current status so it can be restored on unlock.
        Used by the voice pipeline to prevent Claude session status
        from overriding voice feedback states.
        """
        with self._lock:
            self._pre_lock_status = self._state.get("status", {}).copy()
            self._status_locked = True

    def unlock_status(self) -> None:
        """Unlock status updates and restore the pre-lock status."""
        with self._lock:
            self._status_locked = False
            if self._pre_lock_status is not None:
                self._state["status"] = self._pre_lock_status
                self._pre_lock_status = None

    def update(self, section: str, value: dict, force: bool = False) -> None:
        """Update a state section.

        Args:
            section: State section name (status, sessions, weather, etc.)
            value: New value for the section
            force: Bypass status lock (used by voice pipeline)
        """
        with self._lock:
            if section == "status" and self._status_locked and not force:
                return
            self._state[section] = value

    def get(self, section: str) -> dict:
        """
        Get a copy of a state section.

        Args:
            section: State section name

        Returns:
            Copy of the section data (empty dict if not found)
        """
        with self._lock:
            data = self._state.get(section, {})
            # Return deep copy to prevent external mutation of nested dicts
            return copy.deepcopy(data)

    def peek(self, section: str) -> dict:
        """Get a read-only shallow copy of a state section.

        Cheaper than ``get()`` — no deep copy.  Callers must NOT mutate
        the returned dict or its nested values.  Use for read-only hot
        paths like the display render loop.
        """
        with self._lock:
            data = self._state.get(section, {})
            return dict(data)
