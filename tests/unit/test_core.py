"""Tests for core modules: cache, state, and IPC."""

import json
import os
import tempfile
import threading
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from clarvis.core.cache import read_hub_data, write_hub_section, get_hub_section
from clarvis.core.state import StateStore, get_state_store, reset_state_store
from clarvis.core.ipc import DaemonServer, DaemonClient


@pytest.fixture
def temp_hub_file(tmp_path):
    test_file = tmp_path / "test-hub-data.json"
    with patch("clarvis.core.cache.HUB_DATA_FILE", test_file):
        yield test_file


@pytest.fixture
def socket_path():
    fd, path = tempfile.mkstemp(suffix=".sock")
    os.close(fd)
    os.unlink(path)
    yield path
    if os.path.exists(path):
        try:
            os.unlink(path)
        except Exception:
            pass


@pytest.fixture
def ipc_server(socket_path):
    server = DaemonServer(socket_path=socket_path)
    server.start()
    yield server
    server.stop()


class TestCache:
    def test_read_write_get_cycle(self, temp_hub_file):
        """Test complete cache read/write/get workflow."""
        with patch("clarvis.core.cache.HUB_DATA_FILE", temp_hub_file):
            # Empty file returns empty dict
            assert read_hub_data() == {}

            # Write and verify
            write_hub_section("weather", {"temp": 72})
            data = json.loads(temp_hub_file.read_text())
            assert data["weather"]["temp"] == 72
            assert "updated_at" in data["weather"]

            # Get fresh data works
            result = get_hub_section("weather", max_age=60)
            assert result["temp"] == 72

            # Missing section returns None
            assert get_hub_section("nonexistent") is None

    def test_staleness_and_invalid_json(self, temp_hub_file):
        """Test cache handles stale data and invalid JSON."""
        with patch("clarvis.core.cache.HUB_DATA_FILE", temp_hub_file):
            # Invalid JSON returns empty
            temp_hub_file.write_text("not valid json {{{")
            assert read_hub_data() == {}

            # Stale data returns None
            old_time = (datetime.now() - timedelta(seconds=120)).isoformat()
            temp_hub_file.write_text(json.dumps({"weather": {"temp": 72, "updated_at": old_time}}))
            assert get_hub_section("weather", max_age=60) is None
            assert get_hub_section("weather", max_age=200) is not None


class TestStateStore:
    def test_state_operations(self):
        """Test StateStore update, get, batch operations."""
        store = StateStore()

        # Has expected sections
        state = store.get_all()
        for key in ("status", "sessions", "weather", "location", "time"):
            assert key in state

        # Update and get
        store.update("weather", {"temp": 72})
        assert store.get("weather")["temp"] == 72

        # Returns copy, not reference
        result = store.get("weather")
        result["temp"] = 100
        assert store.get("weather")["temp"] == 72

        # Unknown section returns empty dict
        assert store.get("nonexistent") == {}

        # Batch update
        store.batch_update({"weather": {"temp": 80}, "time": {"tz": "PST"}})
        assert store.get("weather")["temp"] == 80
        assert store.get("time")["tz"] == "PST"

    def test_observers(self):
        """Test observer subscribe/notify/unsubscribe pattern."""
        store = StateStore()
        obs1, obs2 = MagicMock(), MagicMock()

        # Subscribe and notify
        unsub1 = store.subscribe(obs1)
        store.subscribe(obs2)
        store.update("weather", {"temp": 72})
        obs1.assert_called_once_with("weather", {"temp": 72})
        obs2.assert_called_once()

        # Unsubscribe works
        unsub1()
        store.update("weather", {"temp": 80})
        assert obs1.call_count == 1  # Not called again
        assert obs2.call_count == 2

        # Silent update doesn't notify
        obs3 = MagicMock()
        store.subscribe(obs3)
        store.update("weather", {"temp": 90}, notify=False)
        obs3.assert_not_called()

    def test_singleton_and_reset(self):
        """Test global singleton behavior."""
        store1 = get_state_store()
        assert get_state_store() is store1

        store1.update("test", {"value": 1})
        reset_state_store()
        store2 = get_state_store()
        assert store1 is not store2
        assert store2.get("test") == {}

    def test_thread_safety(self):
        """Test concurrent updates don't crash."""
        store = StateStore()
        errors = []

        def updater(n):
            try:
                for i in range(50):
                    store.update(f"section_{n}", {"count": i})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=updater, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0


class TestIPC:
    def test_server_lifecycle(self, socket_path):
        """Test server start/stop and socket management."""
        server = DaemonServer(socket_path=socket_path)

        # Start creates socket
        assert not os.path.exists(socket_path)
        server.start()
        assert os.path.exists(socket_path)

        # Stop removes socket
        server.stop()
        assert not os.path.exists(socket_path)

        # Cleans up stale socket
        with open(socket_path, "w") as f:
            f.write("stale")
        server2 = DaemonServer(socket_path=socket_path)
        server2.start()
        assert server2._running
        server2.stop()

    def test_client_server_communication(self, ipc_server, socket_path):
        """Test client-server RPC calls."""
        client = DaemonClient(socket_path=socket_path, timeout=5.0)

        # Check if running
        assert client.is_daemon_running()

        # Simple call
        ipc_server.register("ping", lambda: "pong")
        assert client.call("ping") == "pong"

        # Call with params
        ipc_server.register("add", lambda a, b: a + b)
        assert client.call("add", a=2, b=3) == 5

        # Unknown method raises
        with pytest.raises(RuntimeError, match="Unknown method"):
            client.call("nonexistent")

        # Multiple calls work
        ipc_server.register("echo", lambda msg: msg)
        for i in range(3):
            assert client.call("echo", msg=f"msg-{i}") == f"msg-{i}"

    def test_no_server_errors(self, socket_path):
        """Test client behavior when no server."""
        client = DaemonClient(socket_path=socket_path)
        assert not client.is_daemon_running()
        with pytest.raises(ConnectionError, match="socket not found"):
            client.call("test")


DaemonServer.is_running = property(lambda self: self._running)
