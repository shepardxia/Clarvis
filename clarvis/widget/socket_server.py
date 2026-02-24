"""Unix socket server for bidirectional communication with Swift widget.

Protocol: Newline-delimited JSON messages in both directions.
- Daemon → Widget: grid data (rows/cell_colors/theme_color) or commands (have "method" key)
- Widget → Daemon: results (have "method" key, e.g. "asr_result")
"""

import json
import logging
import socket
import threading
from typing import Callable

try:
    import orjson

    def _serialize_frame(data: dict) -> bytes:
        return orjson.dumps(data) + b"\n"
except ImportError:

    def _serialize_frame(data: dict) -> bytes:
        return json.dumps(data).encode("utf-8") + b"\n"


from ..core.socket_base import UnixSocketServer

logger = logging.getLogger(__name__)

SOCKET_PATH = "/tmp/clarvis-widget.sock"


class WidgetSocketServer(UnixSocketServer):
    """Bidirectional socket server for widget communication."""

    def __init__(self, socket_path: str = SOCKET_PATH):
        super().__init__(socket_path)
        self.clients: list[socket.socket] = []
        self._lock = threading.Lock()
        self._read_threads: list[threading.Thread] = []
        self._message_callback: Callable[[dict], None] | None = None
        self._connect_callback: Callable[[], None] | None = None

    def on_message(self, callback: Callable[[dict], None]) -> None:
        """Register callback for messages received from widget."""
        self._message_callback = callback

    def on_connect(self, callback: Callable[[], None]) -> None:
        """Register callback invoked when a new widget client connects."""
        self._connect_callback = callback

    def stop(self) -> None:  # pragma: no cover
        """Stop the server and close all connections."""
        # Close all client connections first
        with self._lock:
            for client in self.clients:
                try:
                    client.close()
                except Exception:
                    pass
            self.clients.clear()

        super().stop()

        # Wait for read threads
        for t in self._read_threads:
            t.join(timeout=1.0)
        self._read_threads.clear()

    def _on_client_connected(self, client: socket.socket) -> None:  # pragma: no cover
        """Track client and start a reader thread."""
        client.setblocking(True)
        with self._lock:
            self.clients.append(client)
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

    def _read_from_client(self, client: socket.socket) -> None:  # pragma: no cover
        """Read newline-delimited JSON messages from a connected widget."""
        for raw in self.iter_messages(client):
            try:
                message = json.loads(raw)
                if self._message_callback and "method" in message:
                    self._message_callback(message)
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.warning("Bad message from widget: %s", e)

    def push_frame(self, frame_data: dict) -> int:  # pragma: no cover
        """Push a frame to all connected clients.

        Returns:
            Number of clients that received the frame.
        """
        if not self.clients:
            return 0

        msg = _serialize_frame(frame_data)
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
