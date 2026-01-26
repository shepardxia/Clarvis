"""Tests for core modules: cache, state, and IPC."""

import json
import os
import tempfile
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from clarvis.core.cache import read_hub_data, write_hub_section, get_hub_section
from clarvis.core.state import StateStore
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
    def test_read_write_get_with_staleness(self, temp_hub_file):
        """Test cache read/write/get cycle including staleness."""
        with patch("clarvis.core.cache.HUB_DATA_FILE", temp_hub_file):
            assert read_hub_data() == {}
            write_hub_section("weather", {"temp": 72})
            assert get_hub_section("weather", max_age=60)["temp"] == 72
            assert get_hub_section("nonexistent") is None

            # Stale data
            old_time = (datetime.now() - timedelta(seconds=120)).isoformat()
            temp_hub_file.write_text(json.dumps({"weather": {"temp": 72, "updated_at": old_time}}))
            assert get_hub_section("weather", max_age=60) is None


class TestStateStore:
    def test_update_get_and_observers(self):
        """Test state operations and observer pattern."""
        store = StateStore()
        obs = MagicMock()
        unsub = store.subscribe(obs)

        store.update("weather", {"temp": 72})
        assert store.get("weather")["temp"] == 72
        obs.assert_called_once()

        unsub()
        store.update("weather", {"temp": 80})
        assert obs.call_count == 1  # Not called after unsub


class TestIPC:
    def test_server_client_communication(self, ipc_server, socket_path):
        """Test IPC server/client RPC."""
        client = DaemonClient(socket_path=socket_path, timeout=5.0)
        assert client.is_daemon_running()

        ipc_server.register("add", lambda a, b: a + b)
        assert client.call("add", a=2, b=3) == 5

        with pytest.raises(RuntimeError, match="Unknown method"):
            client.call("nonexistent")

    def test_no_server(self, socket_path):
        """Test client when no server running."""
        client = DaemonClient(socket_path=socket_path)
        assert not client.is_daemon_running()
        with pytest.raises(ConnectionError):
            client.call("test")
