"""Unix socket server for pushing frames to Swift widget."""

from __future__ import annotations

import json
import os
import socket
import threading
from pathlib import Path

SOCKET_PATH = "/tmp/clarvis-widget.sock"


class WidgetSocketServer:
    """
    Push display frames to connected Swift widgets via Unix socket.

    Protocol: Newline-delimited JSON messages.
    Each frame is a JSON object followed by newline.
    """

    def __init__(self, socket_path: str = SOCKET_PATH):
        self.socket_path = socket_path
        self.server_socket: socket.socket | None = None
        self.clients: list[socket.socket] = []
        self._lock = threading.Lock()
        self._running = False
        self._accept_thread: threading.Thread | None = None

    def start(self) -> None:
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
        self.server_socket.listen(5)  # Allow a few pending connections
        self.server_socket.settimeout(1.0)  # For clean shutdown

        self._running = True

        # Accept connections in background
        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()

    def stop(self) -> None:
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

        # Clean up socket file
        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except Exception:
                pass

    def _accept_loop(self) -> None:
        """Accept incoming connections."""
        while self._running and self.server_socket:
            try:
                client, _ = self.server_socket.accept()
                client.setblocking(True)
                with self._lock:
                    self.clients.append(client)
            except socket.timeout:
                continue  # Check _running flag
            except OSError:
                break  # Socket closed

    def push_frame(self, frame_data: dict) -> int:
        """
        Push a frame to all connected clients.

        Args:
            frame_data: Frame data dict to send as JSON

        Returns:
            Number of clients that received the frame
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

            # Remove dead clients
            for client in dead_clients:
                try:
                    client.close()
                except Exception:
                    pass
                if client in self.clients:
                    self.clients.remove(client)

        return sent_count

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
