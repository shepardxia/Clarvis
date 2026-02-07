"""Single source of truth for all Clarvis state with observer pattern."""

import logging
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class StateStore:
    """
    Central state store with observer pattern.

    All state changes go through this class. Observers are notified
    when state changes, enabling push-based updates.
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
        self._observers: list[Callable[[str, dict], None]] = []
        self._lock = threading.RLock()  # Reentrant for nested calls
        self._status_locked = False
        self._pre_lock_status: dict | None = None

    def subscribe(self, callback: Callable[[str, dict], None]) -> Callable[[], None]:
        """
        Subscribe to state changes.

        Args:
            callback: Function called with (section, new_value) on changes

        Returns:
            Unsubscribe function
        """
        with self._lock:
            self._observers.append(callback)

        def unsubscribe():
            with self._lock:
                if callback in self._observers:
                    self._observers.remove(callback)

        return unsubscribe

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

    def update(self, section: str, value: dict, notify: bool = True, force: bool = False) -> None:
        """
        Update a state section and notify observers.

        Args:
            section: State section name (status, sessions, weather, etc.)
            value: New value for the section
            notify: Whether to notify observers (default True)
            force: Bypass status lock (used by voice pipeline)
        """
        with self._lock:
            if section == "status" and self._status_locked and not force:
                return
            self._state[section] = value
            observers = self._observers.copy()  # Copy to avoid mutation during iteration

        if notify:
            for observer in observers:
                try:
                    observer(section, value)
                except Exception as e:
                    logger.warning(f"Observer failed for section '{section}': {e}")

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
            # Return copy to prevent external mutation
            return data.copy() if isinstance(data, dict) else data

    def get_all(self) -> dict[str, dict]:
        """
        Get a copy of all state.

        Returns:
            Copy of entire state dict
        """
        with self._lock:
            return {k: v.copy() if isinstance(v, dict) else v for k, v in self._state.items()}

    def batch_update(self, updates: dict[str, dict]) -> None:
        """
        Update multiple sections atomically, notify once per section.

        Args:
            updates: Dict of {section: value} to update
        """
        with self._lock:
            for section, value in updates.items():
                self._state[section] = value
            observers = self._observers.copy()

        # Notify after all updates complete
        for section, value in updates.items():
            for observer in observers:
                try:
                    observer(section, value)
                except Exception as e:
                    logger.warning(f"Observer failed for section '{section}': {e}")


# Global instance for singleton access
_store_instance: Optional[StateStore] = None
_store_lock = threading.Lock()


def get_state_store() -> StateStore:
    """Get or create the global StateStore instance."""
    global _store_instance
    if _store_instance is None:
        with _store_lock:
            if _store_instance is None:
                _store_instance = StateStore()
    return _store_instance
