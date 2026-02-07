"""Unix socket server for bidirectional communication with Swift widget.

Protocol: Newline-delimited JSON messages in both directions.
- Daemon → Widget: grid data (rows/cell_colors/theme_color) or commands (have "method" key)
- Widget → Daemon: results (have "method" key, e.g. "asr_result")
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
from typing import Callable

logger = logging.getLogger(__name__)

SOCKET_PATH = "/tmp/clarvis-widget.sock"


class WidgetSocketServer:
    """Bidirectional socket server for widget communication."""

    def __init__(self, socket_path: str = SOCKET_PATH):
        self.socket_path = socket_path
        self.server_socket: socket.socket | None = None
        self.clients: list[socket.socket] = []
        self._lock = threading.Lock()
        self._running = False
        self._accept_thread: threading.Thread | None = None
        self._read_threads: list[threading.Thread] = []
        self._message_callback: Callable[[dict], None] | None = None
        self._connect_callback: Callable[[], None] | None = None

    def on_message(self, callback: Callable[[dict], None]) -> None:
        """Register callback for messages received from widget."""
        self._message_callback = callback

    def on_connect(self, callback: Callable[[], None]) -> None:
        """Register callback invoked when a new widget client connects."""
        self._connect_callback = callback

    def start(self) -> None:  # pragma: no cover
        """Start the socket server and begin accepting connections."""
        if self._running:
            return

        # Clean up stale socket file
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)

        # Create Unix socket
        self.server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind(self.socket_path)
        self.server_socket.listen(5)
        self.server_socket.settimeout(1.0)

        self._running = True

        # Accept connections in background
        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()

    def stop(self) -> None:  # pragma: no cover
        """Stop the server and close all connections."""
        self._running = False

        # Close all client connections
        with self._lock:
            for client in self.clients:
                try:
                    client.close()
                except Exception:
                    pass
            self.clients.clear()

        # Close server socket
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
            self.server_socket = None

        # Wait for accept thread
        if self._accept_thread:
            self._accept_thread.join(timeout=2.0)
            self._accept_thread = None

        # Wait for read threads
        for t in self._read_threads:
            t.join(timeout=1.0)
        self._read_threads.clear()

        # Clean up socket file
        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except Exception:
                pass

    def _accept_loop(self) -> None:  # pragma: no cover
        """Accept incoming connections and start read threads."""
        while self._running and self.server_socket:
            try:
                client, _ = self.server_socket.accept()
                client.setblocking(True)
                with self._lock:
                    self.clients.append(client)
                # Start a read thread for this client
                t = threading.Thread(
                    target=self._read_from_client,
                    args=(client,),
                    daemon=True,
                )
                t.start()
                self._read_threads.append(t)
                if self._connect_callback:
                    try:
                        self._connect_callback()
                    except Exception:
                        logger.exception("Error in connect callback")
            except socket.timeout:
                continue
            except OSError:
                break

    def _read_from_client(self, client: socket.socket) -> None:  # pragma: no cover
        """Read newline-delimited JSON messages from a connected widget."""
        buffer = b""
        try:
            while self._running:
                chunk = client.recv(4096)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line:
                        continue
                    try:
                        message = json.loads(line.decode("utf-8"))
                        if self._message_callback and "method" in message:
                            self._message_callback(message)
                    except (json.JSONDecodeError, UnicodeDecodeError) as e:
                        logger.warning("Bad message from widget: %s", e)
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass

    def push_frame(self, frame_data: dict) -> int:  # pragma: no cover
        """Push a frame to all connected clients.

        Returns:
            Number of clients that received the frame.
        """
        if not self.clients:
            return 0

        msg = json.dumps(frame_data).encode("utf-8") + b"\n"
        sent_count = 0
        dead_clients = []

        with self._lock:
            for client in self.clients:
                try:
                    client.sendall(msg)
                    sent_count += 1
                except (BrokenPipeError, ConnectionResetError, OSError):
                    dead_clients.append(client)

            for client in dead_clients:
                try:
                    client.close()
                except Exception:
                    pass
                if client in self.clients:
                    self.clients.remove(client)

        return sent_count

    def send_command(self, command: dict) -> int:  # pragma: no cover
        """Send a command to all connected widgets.

        Commands are JSON objects with a "method" key.
        Uses the same transport as push_frame.
        """
        return self.push_frame(command)

    @property
    def client_count(self) -> int:
        """Number of connected clients."""
        with self._lock:
            return len(self.clients)

    @property
    def is_running(self) -> bool:
        """Whether the server is running."""
        return self._running


# Global instance
_server_instance: WidgetSocketServer | None = None
_server_lock = threading.Lock()


def get_socket_server() -> WidgetSocketServer:
    """Get or create the global socket server instance."""
    global _server_instance
    if _server_instance is None:
        with _server_lock:
            if _server_instance is None:
                _server_instance = WidgetSocketServer()
    return _server_instance


def reset_socket_server() -> None:
    """Reset the global socket server instance. Used for testing."""
    global _server_instance
    with _server_lock:
        if _server_instance is not None:
            _server_instance.stop()
            _server_instance = None
