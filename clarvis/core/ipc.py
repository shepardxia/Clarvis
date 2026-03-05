"""IPC protocol for daemon communication.

JSON-RPC style protocol over Unix socket.
Request:      {"method": "name", "params": {...}}  → response sent
Notification: {"method": "name", "params": {...}, "notify": true}  → no response
"""

import json
import os
import socket
import threading
from typing import Any, Callable

from .socket_base import UnixSocketServer

COMMAND_SOCKET_PATH = "/tmp/clarvis-daemon.sock"


class DaemonServer(UnixSocketServer):
    """
    Command server that runs inside the daemon.
    Handles requests from MCP and other clients.
    """

    def __init__(self, socket_path: str = COMMAND_SOCKET_PATH):
        super().__init__(socket_path)
        self._handlers: dict[str, Callable[..., Any]] = {}

    def register(self, method: str, handler: Callable[..., Any]) -> None:
        """Register a method handler."""
        self._handlers[method] = handler

    def _on_client_connected(self, client: socket.socket) -> None:
        """Spawn a thread per client connection."""
        threading.Thread(target=self._handle_client, args=(client,), daemon=True).start()

    def _handle_client(self, client: socket.socket) -> None:
        """Handle a single client connection."""
        try:
            client.settimeout(180.0)
            for message in self.iter_messages(client):
                response = self._process_request(message)
                if response is not None:
                    client.sendall(response.encode("utf-8") + b"\n")
        except socket.timeout:
            pass
        finally:
            try:
                client.close()
            except Exception:
                pass

    def _process_request(self, request_str: str) -> str | None:
        """Process a JSON request. Returns response string, or None for notifications."""
        is_notify = False
        try:
            request = json.loads(request_str)
            method = request.get("method")
            params = request.get("params", {})
            is_notify = request.get("notify", False)

            if not method:
                return None if is_notify else json.dumps({"error": "Missing method"})

            handler = self._handlers.get(method)
            if not handler:
                return None if is_notify else json.dumps({"error": f"Unknown method: {method}"})

            result = handler(**params)
            if is_notify:
                return None
            return json.dumps({"result": result})

        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid JSON: {e}"})
        except TypeError as e:
            return None if is_notify else json.dumps({"error": f"Invalid params: {e}"})
        except Exception as e:
            return None if is_notify else json.dumps({"error": str(e)})


class DaemonClient:
    """
    Client for communicating with the daemon.
    Used by MCP server and other external processes.
    """

    def __init__(self, socket_path: str = COMMAND_SOCKET_PATH, timeout: float = 30.0):
        self.socket_path = socket_path
        self.timeout = timeout

    def is_daemon_running(self) -> bool:
        """Check if daemon is running by testing socket connection."""
        if not os.path.exists(self.socket_path):
            return False
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.settimeout(1.0)
            sock.connect(self.socket_path)
            return True
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            return False
        finally:
            sock.close()

    def call(self, method: str, **params) -> Any:
        """
        Call a daemon method and return the result.

        Args:
            method: Method name to call
            **params: Parameters to pass

        Returns:
            Result from the daemon

        Raises:
            ConnectionError: If daemon is not running
            RuntimeError: If daemon returns an error
        """
        if not os.path.exists(self.socket_path):
            raise ConnectionError("Daemon not running (socket not found)")

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)

        try:
            sock.connect(self.socket_path)

            # Send request
            request = json.dumps({"method": method, "params": params})
            sock.sendall(request.encode("utf-8") + b"\n")

            # Read response
            buffer = b""
            while b"\n" not in buffer:
                chunk = sock.recv(4096)
                if not chunk:
                    raise ConnectionError("Connection closed by daemon")
                buffer += chunk

            response_str = buffer.split(b"\n")[0].decode("utf-8")
            response = json.loads(response_str)

            if "error" in response:
                raise RuntimeError(response["error"])

            return response.get("result")

        except socket.timeout:
            raise ConnectionError("Daemon request timed out")
        except ConnectionRefusedError:
            raise ConnectionError("Daemon not running (connection refused)")
        finally:
            try:
                sock.close()
            except Exception:
                pass
