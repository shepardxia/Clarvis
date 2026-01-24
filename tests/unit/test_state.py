"""Tests for StateStore with observer pattern."""

import logging
import pytest
import threading
from unittest.mock import MagicMock

from clarvis.core.state import (
    StateStore,
    get_state_store,
    reset_state_store,
)


class TestStateStore:
    """Tests for StateStore class."""

    def test_initial_state_sections(self):
        """Should have default state sections."""
        store = StateStore()
        state = store.get_all()
        assert "status" in state
        assert "sessions" in state
        assert "weather" in state
        assert "location" in state
        assert "time" in state

    def test_update_and_get(self):
        """Should update and retrieve state."""
        store = StateStore()
        store.update("weather", {"temp": 72})
        result = store.get("weather")
        assert result["temp"] == 72

    def test_get_returns_copy(self):
        """Should return a copy to prevent mutation."""
        store = StateStore()
        store.update("weather", {"temp": 72})
        result = store.get("weather")
        result["temp"] = 100  # Mutate the copy
        assert store.get("weather")["temp"] == 72  # Original unchanged

    def test_get_unknown_section(self):
        """Should return empty dict for unknown section."""
        store = StateStore()
        result = store.get("nonexistent")
        assert result == {}

    def test_get_all_returns_copy(self):
        """Should return copies of all sections."""
        store = StateStore()
        store.update("weather", {"temp": 72})
        all_state = store.get_all()
        all_state["weather"]["temp"] = 100
        assert store.get("weather")["temp"] == 72

    def test_update_without_notify(self):
        """Should skip observer notification when notify=False."""
        store = StateStore()
        observer = MagicMock()
        store.subscribe(observer)

        store.update("weather", {"temp": 72}, notify=False)

        observer.assert_not_called()
        assert store.get("weather")["temp"] == 72


class TestStateStoreObservers:
    """Tests for observer pattern."""

    def test_subscribe_and_notify(self):
        """Should notify observers on update."""
        store = StateStore()
        observer = MagicMock()
        store.subscribe(observer)

        store.update("weather", {"temp": 72})

        observer.assert_called_once_with("weather", {"temp": 72})

    def test_multiple_observers(self):
        """Should notify all observers."""
        store = StateStore()
        observer1 = MagicMock()
        observer2 = MagicMock()
        store.subscribe(observer1)
        store.subscribe(observer2)

        store.update("weather", {"temp": 72})

        observer1.assert_called_once()
        observer2.assert_called_once()

    def test_unsubscribe(self):
        """Should stop notifying after unsubscribe."""
        store = StateStore()
        observer = MagicMock()
        unsubscribe = store.subscribe(observer)

        store.update("weather", {"temp": 72})
        assert observer.call_count == 1

        unsubscribe()
        store.update("weather", {"temp": 80})
        assert observer.call_count == 1  # Not called again

    def test_unsubscribe_idempotent(self):
        """Should handle multiple unsubscribe calls."""
        store = StateStore()
        observer = MagicMock()
        unsubscribe = store.subscribe(observer)

        unsubscribe()
        unsubscribe()  # Should not raise

    def test_observer_exception_logged(self, caplog):
        """Should log warning when observer raises exception."""
        store = StateStore()

        def failing_observer(section, value):
            raise ValueError("Observer error")

        store.subscribe(failing_observer)

        with caplog.at_level(logging.WARNING):
            store.update("weather", {"temp": 72})

        assert "Observer failed" in caplog.text
        assert "Observer error" in caplog.text

    def test_observer_exception_doesnt_break_others(self):
        """Should continue notifying other observers after one fails."""
        store = StateStore()

        def failing_observer(section, value):
            raise ValueError("Observer error")

        good_observer = MagicMock()

        store.subscribe(failing_observer)
        store.subscribe(good_observer)

        store.update("weather", {"temp": 72})

        good_observer.assert_called_once()


class TestStateStoreBatchUpdate:
    """Tests for batch_update method."""

    def test_batch_update_multiple_sections(self):
        """Should update multiple sections atomically."""
        store = StateStore()
        store.batch_update({
            "weather": {"temp": 72},
            "time": {"tz": "PST"},
        })

        assert store.get("weather")["temp"] == 72
        assert store.get("time")["tz"] == "PST"

    def test_batch_update_notifies_observers(self):
        """Should notify observers for each section."""
        store = StateStore()
        calls = []

        def observer(section, value):
            calls.append((section, value))

        store.subscribe(observer)
        store.batch_update({
            "weather": {"temp": 72},
            "time": {"tz": "PST"},
        })

        assert len(calls) == 2
        sections = [c[0] for c in calls]
        assert "weather" in sections
        assert "time" in sections

    def test_batch_update_observer_exception_logged(self, caplog):
        """Should log warning when observer fails during batch update."""
        store = StateStore()

        def failing_observer(section, value):
            raise ValueError("Batch observer error")

        store.subscribe(failing_observer)

        with caplog.at_level(logging.WARNING):
            store.batch_update({"weather": {"temp": 72}})

        assert "Observer failed" in caplog.text


class TestGlobalStateStore:
    """Tests for global singleton functions."""

    def test_get_state_store_returns_same_instance(self):
        """Should return same instance on multiple calls."""
        store1 = get_state_store()
        store2 = get_state_store()
        assert store1 is store2

    def test_reset_creates_new_instance(self):
        """Should create new instance after reset."""
        store1 = get_state_store()
        store1.update("test", {"value": 1})

        reset_state_store()
        store2 = get_state_store()

        assert store1 is not store2
        assert store2.get("test") == {}


class TestStateStoreThreadSafety:
    """Tests for thread safety."""

    def test_concurrent_updates(self):
        """Should handle concurrent updates safely."""
        store = StateStore()
        errors = []

        def updater(n):
            try:
                for i in range(100):
                    store.update(f"section_{n}", {"count": i})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=updater, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_concurrent_subscribe_unsubscribe(self):
        """Should handle concurrent subscribe/unsubscribe safely."""
        store = StateStore()
        errors = []

        def subscriber():
            try:
                for _ in range(50):
                    unsub = store.subscribe(lambda s, v: None)
                    unsub()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=subscriber) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
