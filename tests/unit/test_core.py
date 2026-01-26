"""Tests for core modules: cache, state, and IPC."""

import json
import logging
import os
import socket
import tempfile
import threading
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from clarvis.core.cache import (
    read_hub_data,
    write_hub_section,
    get_hub_section,
)
from clarvis.core.state import StateStore, get_state_store, reset_state_store
from clarvis.core.ipc import DaemonServer, DaemonClient


# =============================================================================
# Cache Tests
# =============================================================================


@pytest.fixture
def temp_hub_file(tmp_path):
    """Use a temporary file for hub data."""
    test_file = tmp_path / "test-hub-data.json"
    with patch("clarvis.core.cache.HUB_DATA_FILE", test_file):
        yield test_file


class TestCache:
    """Tests for file-based caching utilities."""

    def test_read_returns_empty_when_missing(self, temp_hub_file):
        with patch("clarvis.core.cache.HUB_DATA_FILE", temp_hub_file):
            assert read_hub_data() == {}

    def test_read_existing_data(self, temp_hub_file):
        test_data = {"weather": {"temp": 72}, "time": {"tz": "PST"}}
        temp_hub_file.write_text(json.dumps(test_data))
        with patch("clarvis.core.cache.HUB_DATA_FILE", temp_hub_file):
            assert read_hub_data() == test_data

    def test_read_handles_invalid_json(self, temp_hub_file):
        temp_hub_file.write_text("not valid json {{{")
        with patch("clarvis.core.cache.HUB_DATA_FILE", temp_hub_file):
            assert read_hub_data() == {}

    def test_write_new_section(self, temp_hub_file):
        with patch("clarvis.core.cache.HUB_DATA_FILE", temp_hub_file):
            write_hub_section("weather", {"temp": 72, "humidity": 50})
        data = json.loads(temp_hub_file.read_text())
        assert data["weather"]["temp"] == 72
        assert "updated_at" in data["weather"]

    def test_write_preserves_other_sections(self, temp_hub_file):
        initial = {"time": {"tz": "PST", "updated_at": "2024-01-01T00:00:00"}}
        temp_hub_file.write_text(json.dumps(initial))
        with patch("clarvis.core.cache.HUB_DATA_FILE", temp_hub_file):
            write_hub_section("weather", {"temp": 72})
        data = json.loads(temp_hub_file.read_text())
        assert data["time"]["tz"] == "PST"
        assert "weather" in data

    def test_get_returns_none_for_missing(self, temp_hub_file):
        temp_hub_file.write_text(json.dumps({}))
        with patch("clarvis.core.cache.HUB_DATA_FILE", temp_hub_file):
            assert get_hub_section("nonexistent") is None

    def test_get_returns_fresh_data(self, temp_hub_file):
        now = datetime.now().isoformat()
        data = {"weather": {"temp": 72, "updated_at": now}}
        temp_hub_file.write_text(json.dumps(data))
        with patch("clarvis.core.cache.HUB_DATA_FILE", temp_hub_file):
            result = get_hub_section("weather", max_age=60)
        assert result["temp"] == 72

    def test_get_returns_none_for_stale(self, temp_hub_file):
        old_time = (datetime.now() - timedelta(seconds=120)).isoformat()
        data = {"weather": {"temp": 72, "updated_at": old_time}}
        temp_hub_file.write_text(json.dumps(data))
        with patch("clarvis.core.cache.HUB_DATA_FILE", temp_hub_file):
            assert get_hub_section("weather", max_age=60) is None

    def test_get_respects_custom_max_age(self, temp_hub_file):
        old_time = (datetime.now() - timedelta(seconds=90)).isoformat()
        data = {"weather": {"temp": 72, "updated_at": old_time}}
        temp_hub_file.write_text(json.dumps(data))
        with patch("clarvis.core.cache.HUB_DATA_FILE", temp_hub_file):
            assert get_hub_section("weather", max_age=60) is None
            assert get_hub_section("weather", max_age=120) is not None


# =============================================================================
# State Tests
# =============================================================================


class TestStateStore:
    """Tests for StateStore class."""

    def test_initial_state_sections(self):
        store = StateStore()
        state = store.get_all()
        for key in ("status", "sessions", "weather", "location", "time"):
            assert key in state

    def test_update_and_get(self):
        store = StateStore()
        store.update("weather", {"temp": 72})
        assert store.get("weather")["temp"] == 72

    def test_get_returns_copy(self):
        store = StateStore()
        store.update("weather", {"temp": 72})
        result = store.get("weather")
        result["temp"] = 100
        assert store.get("weather")["temp"] == 72

    def test_get_unknown_section(self):
        assert StateStore().get("nonexistent") == {}

    def test_update_without_notify(self):
        store = StateStore()
        observer = MagicMock()
        store.subscribe(observer)
        store.update("weather", {"temp": 72}, notify=False)
        observer.assert_not_called()


class TestStateObservers:
    """Tests for observer pattern."""

    def test_subscribe_and_notify(self):
        store = StateStore()
        observer = MagicMock()
        store.subscribe(observer)
        store.update("weather", {"temp": 72})
        observer.assert_called_once_with("weather", {"temp": 72})

    def test_multiple_observers(self):
        store = StateStore()
        obs1, obs2 = MagicMock(), MagicMock()
        store.subscribe(obs1)
        store.subscribe(obs2)
        store.update("weather", {"temp": 72})
        obs1.assert_called_once()
        obs2.assert_called_once()

    def test_unsubscribe(self):
        store = StateStore()
        observer = MagicMock()
        unsub = store.subscribe(observer)
        store.update("weather", {"temp": 72})
        unsub()
        store.update("weather", {"temp": 80})
        assert observer.call_count == 1

    def test_observer_exception_logged(self, caplog):
        store = StateStore()
        store.subscribe(lambda s, v: (_ for _ in ()).throw(ValueError("fail")))
        with caplog.at_level(logging.WARNING):
            store.update("weather", {"temp": 72})
        assert "Observer failed" in caplog.text

    def test_observer_exception_doesnt_break_others(self):
        store = StateStore()
        store.subscribe(lambda s, v: (_ for _ in ()).throw(ValueError()))
        good = MagicMock()
        store.subscribe(good)
        store.update("weather", {"temp": 72})
        good.assert_called_once()


class TestStateBatchUpdate:
    """Tests for batch_update method."""

    def test_batch_update_multiple_sections(self):
        store = StateStore()
        store.batch_update({"weather": {"temp": 72}, "time": {"tz": "PST"}})
        assert store.get("weather")["temp"] == 72
        assert store.get("time")["tz"] == "PST"

    def test_batch_update_notifies_observers(self):
        store = StateStore()
        calls = []
        store.subscribe(lambda s, v: calls.append(s))
        store.batch_update({"weather": {"temp": 72}, "time": {"tz": "PST"}})
        assert set(calls) == {"weather", "time"}


class TestGlobalStateStore:
    """Tests for global singleton functions."""

    def test_returns_same_instance(self):
        assert get_state_store() is get_state_store()

    def test_reset_creates_new_instance(self):
        store1 = get_state_store()
        store1.update("test", {"value": 1})
        reset_state_store()
        store2 = get_state_store()
        assert store1 is not store2
        assert store2.get("test") == {}


class TestStateThreadSafety:
    """Tests for thread safety."""

    def test_concurrent_updates(self):
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


# =============================================================================
# IPC Tests
# =============================================================================


@pytest.fixture
def socket_path():
    """Generate a unique socket path for each test."""
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
    """Create and start a test server."""
    server = DaemonServer(socket_path=socket_path)
    server.start()
    yield server
    server.stop()


@pytest.fixture
def ipc_client(socket_path):
    """Create a test client."""
    return DaemonClient(socket_path=socket_path, timeout=5.0)


class TestDaemonServer:
    """Tests for DaemonServer."""

    def test_start_creates_socket(self, socket_path):
        server = DaemonServer(socket_path=socket_path)
        assert not os.path.exists(socket_path)
        server.start()
        try:
            assert os.path.exists(socket_path)
        finally:
            server.stop()

    def test_stop_removes_socket(self, socket_path):
        server = DaemonServer(socket_path=socket_path)
        server.start()
        server.stop()
        assert not os.path.exists(socket_path)

    def test_register_handler(self, socket_path):
        server = DaemonServer(socket_path=socket_path)
        handler = lambda: "test"
        server.register("test_method", handler)
        assert server._handlers["test_method"] is handler

    def test_cleans_up_stale_socket(self, socket_path):
        with open(socket_path, "w") as f:
            f.write("stale")
        server = DaemonServer(socket_path=socket_path)
        server.start()
        try:
            assert server._running
        finally:
            server.stop()


class TestDaemonClient:
    """Tests for DaemonClient."""

    def test_is_daemon_running_false_when_no_socket(self, socket_path):
        client = DaemonClient(socket_path=socket_path)
        assert not client.is_daemon_running()

    def test_is_daemon_running_true_when_server_running(self, ipc_server, ipc_client):
        assert ipc_client.is_daemon_running()

    def test_call_raises_when_no_socket(self, socket_path):
        client = DaemonClient(socket_path=socket_path)
        with pytest.raises(ConnectionError, match="socket not found"):
            client.call("test")

    def test_call_simple_method(self, ipc_server, ipc_client):
        ipc_server.register("ping", lambda: "pong")
        assert ipc_client.call("ping") == "pong"

    def test_call_method_with_params(self, ipc_server, ipc_client):
        ipc_server.register("add", lambda a, b: a + b)
        assert ipc_client.call("add", a=2, b=3) == 5

    def test_call_unknown_method_raises(self, ipc_server, ipc_client):
        with pytest.raises(RuntimeError, match="Unknown method"):
            ipc_client.call("nonexistent")


class TestIPCIntegration:
    """Integration tests for server-client communication."""

    def test_multiple_calls(self, ipc_server, ipc_client):
        ipc_server.register("echo", lambda msg: msg)
        for i in range(5):
            assert ipc_client.call("echo", msg=f"msg-{i}") == f"msg-{i}"

    def test_concurrent_clients(self, ipc_server, socket_path):
        ipc_server.register("identify", lambda cid: f"client-{cid}")
        results, errors = [], []

        def worker(cid):
            try:
                client = DaemonClient(socket_path=socket_path, timeout=5.0)
                results.append(client.call("identify", cid=cid))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert len(errors) == 0
        assert set(results) == {f"client-{i}" for i in range(5)}

    def test_large_response(self, ipc_server, ipc_client):
        large_data = {"items": [f"item-{i}" for i in range(1000)]}
        ipc_server.register("get_large", lambda: large_data)
        result = ipc_client.call("get_large")
        assert len(result["items"]) == 1000


# Add is_running property for tests
DaemonServer.is_running = property(lambda self: self._running)
