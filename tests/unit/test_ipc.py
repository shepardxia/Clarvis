"""Tests for IPC protocol (DaemonServer and DaemonClient)."""

import json
import os
import socket
import tempfile
import threading
import time

import pytest

from central_hub.core.ipc import DaemonServer, DaemonClient


@pytest.fixture
def socket_path():
    """Generate a unique socket path for each test."""
    # Use tempfile to get a unique path
    fd, path = tempfile.mkstemp(suffix=".sock")
    os.close(fd)
    os.unlink(path)  # Remove the file, we just want the path
    yield path
    # Cleanup
    if os.path.exists(path):
        try:
            os.unlink(path)
        except Exception:
            pass


@pytest.fixture
def server(socket_path):
    """Create and start a test server."""
    server = DaemonServer(socket_path=socket_path)
    server.start()
    yield server
    server.stop()


@pytest.fixture
def client(socket_path):
    """Create a test client."""
    return DaemonClient(socket_path=socket_path, timeout=5.0)


class TestDaemonServer:
    """Tests for DaemonServer."""

    def test_start_creates_socket(self, socket_path):
        """Server start should create socket file."""
        server = DaemonServer(socket_path=socket_path)
        assert not os.path.exists(socket_path)

        server.start()
        try:
            assert os.path.exists(socket_path)
            assert server.is_running
        finally:
            server.stop()

    def test_stop_removes_socket(self, socket_path):
        """Server stop should remove socket file."""
        server = DaemonServer(socket_path=socket_path)
        server.start()
        assert os.path.exists(socket_path)

        server.stop()
        assert not os.path.exists(socket_path)
        assert not server.is_running

    def test_register_handler(self, socket_path):
        """Should be able to register method handlers."""
        server = DaemonServer(socket_path=socket_path)
        handler = lambda: "test"
        server.register("test_method", handler)

        assert "test_method" in server._handlers
        assert server._handlers["test_method"] is handler

    def test_double_start_is_safe(self, socket_path):
        """Starting twice should be safe."""
        server = DaemonServer(socket_path=socket_path)
        server.start()
        try:
            server.start()  # Should not raise
            assert server.is_running
        finally:
            server.stop()

    def test_cleans_up_stale_socket(self, socket_path):
        """Should clean up stale socket file on start."""
        # Create a stale socket file
        with open(socket_path, "w") as f:
            f.write("stale")

        server = DaemonServer(socket_path=socket_path)
        server.start()
        try:
            assert server.is_running
        finally:
            server.stop()

    @property
    def is_running(self):
        """Expose running state for tests."""
        return self._running


class TestDaemonClient:
    """Tests for DaemonClient."""

    def test_is_daemon_running_false_when_no_socket(self, socket_path):
        """Should return False when socket doesn't exist."""
        client = DaemonClient(socket_path=socket_path)
        assert not client.is_daemon_running()

    def test_is_daemon_running_true_when_server_running(self, server, client):
        """Should return True when server is running."""
        assert client.is_daemon_running()

    def test_call_raises_when_no_socket(self, socket_path):
        """Should raise ConnectionError when socket doesn't exist."""
        client = DaemonClient(socket_path=socket_path)
        with pytest.raises(ConnectionError, match="socket not found"):
            client.call("test")

    def test_call_simple_method(self, server, client):
        """Should be able to call a simple method."""
        server.register("ping", lambda: "pong")
        result = client.call("ping")
        assert result == "pong"

    def test_call_method_with_params(self, server, client):
        """Should pass parameters to method."""
        server.register("add", lambda a, b: a + b)
        result = client.call("add", a=2, b=3)
        assert result == 5

    def test_call_method_returning_dict(self, server, client):
        """Should handle dict return values."""
        server.register("get_data", lambda: {"status": "ok", "count": 42})
        result = client.call("get_data")
        assert result == {"status": "ok", "count": 42}

    def test_call_unknown_method_raises(self, server, client):
        """Should raise RuntimeError for unknown method."""
        with pytest.raises(RuntimeError, match="Unknown method"):
            client.call("nonexistent")

    def test_call_missing_method_raises(self, server, client):
        """Should raise RuntimeError when method is missing."""
        # Send raw request without method
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(client.socket_path)
        try:
            sock.sendall(b'{"params": {}}\n')
            response = sock.recv(4096).decode("utf-8")
            data = json.loads(response.strip())
            assert "error" in data
            assert "Missing method" in data["error"]
        finally:
            sock.close()

    def test_call_invalid_params_raises(self, server, client):
        """Should raise RuntimeError for invalid params."""
        server.register("greet", lambda name: f"Hello {name}")
        with pytest.raises(RuntimeError, match="Invalid params"):
            client.call("greet", wrong_param="test")

    def test_call_handler_exception_raises(self, server, client):
        """Should propagate handler exceptions."""
        def failing_handler():
            raise ValueError("Something went wrong")

        server.register("fail", failing_handler)
        with pytest.raises(RuntimeError, match="Something went wrong"):
            client.call("fail")


class TestServerClientIntegration:
    """Integration tests for server-client communication."""

    def test_multiple_calls(self, server, client):
        """Should handle multiple sequential calls."""
        server.register("echo", lambda msg: msg)

        for i in range(5):
            result = client.call("echo", msg=f"message-{i}")
            assert result == f"message-{i}"

    def test_concurrent_clients(self, server, socket_path):
        """Should handle multiple concurrent clients."""
        server.register("identify", lambda client_id: f"client-{client_id}")

        results = []
        errors = []

        def client_worker(client_id):
            try:
                client = DaemonClient(socket_path=socket_path, timeout=5.0)
                result = client.call("identify", client_id=client_id)
                results.append(result)
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(5):
            t = threading.Thread(target=client_worker, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=5.0)

        assert len(errors) == 0, f"Errors: {errors}"
        assert len(results) == 5
        assert set(results) == {f"client-{i}" for i in range(5)}

    def test_invalid_json_returns_error(self, server, socket_path):
        """Should handle malformed JSON gracefully."""
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(socket_path)
        try:
            sock.sendall(b"not valid json\n")
            response = sock.recv(4096).decode("utf-8")
            data = json.loads(response.strip())
            assert "error" in data
            assert "Invalid JSON" in data["error"]
        finally:
            sock.close()

    def test_large_response(self, server, client):
        """Should handle large responses."""
        large_data = {"items": [f"item-{i}" for i in range(1000)]}
        server.register("get_large", lambda: large_data)

        result = client.call("get_large")
        assert result == large_data
        assert len(result["items"]) == 1000


# Add is_running property to DaemonServer for test assertions
DaemonServer.is_running = property(lambda self: self._running)
