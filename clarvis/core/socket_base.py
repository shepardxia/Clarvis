"""Base class for Unix socket servers with shared lifecycle management."""

import logging
import os
import socket
import threading

logger = logging.getLogger(__name__)


class UnixSocketServer:
    """Base class providing Unix socket setup, accept loop, and teardown.

    Subclasses implement :meth:`_on_client_connected` to handle each accepted
    connection (e.g. spawn a handler thread, track persistent clients, etc.).
    """

    def __init__(self, socket_path: str) -> None:
        self.socket_path = socket_path
        self.server_socket: socket.socket | None = None
        self._running = False
        self._accept_thread: threading.Thread | None = None

    # -- Lifecycle -----------------------------------------------------------

    def start(self) -> None:
        """Bind, listen, and begin accepting connections."""
        if self._running:
            return

        # Clean up stale socket
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)

        self.server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind(self.socket_path)
        self.server_socket.listen(5)
        self.server_socket.settimeout(1.0)

        self._running = True
        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()

    def stop(self) -> None:
        """Stop accepting connections and clean up the socket file.

        Subclasses that track clients or extra threads should override this,
        call ``super().stop()``, and then join their own resources.
        """
        self._running = False

        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
            self.server_socket = None

        if self._accept_thread:
            self._accept_thread.join(timeout=2.0)
            self._accept_thread = None

        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except Exception:
                pass

    # -- Accept loop ---------------------------------------------------------

    def _accept_loop(self) -> None:
        """Accept connections in a loop, delegating to subclass hook."""
        while self._running and self.server_socket:
            try:
                client, _ = self.server_socket.accept()
                self._on_client_connected(client)
            except socket.timeout:
                continue
            except OSError:
                break

    def _on_client_connected(self, client: socket.socket) -> None:
        """Handle a newly accepted client.  Override in subclasses."""
        raise NotImplementedError

    # -- Helpers -------------------------------------------------------------

    @staticmethod
    def iter_messages(client: socket.socket, running: threading.Event | None = None) -> str:
        """Yield newline-delimited messages from *client*.

        Stops when the connection closes or *running* (if given) is cleared.
        """
        buffer = b""
        try:
            while True:
                if running is not None and not running.is_set():
                    break
                chunk = client.recv(4096)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if line:
                        yield line.decode("utf-8")
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass
