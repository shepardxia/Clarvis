"""Self-contained agent -- owns session, backend, lifecycle.

Each channel (voice, Discord, etc.) gets its own Agent instance with
a fixed session key, its own PiBackend connection, and retry logic.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator

from .backends.pi import PiBackend, PiConfig

logger = logging.getLogger(__name__)


class Agent:
    """Self-contained agent with full lifecycle management.

    Each channel (voice, Discord, etc.) gets its own Agent with a fixed
    session key.  Constructs and owns its PiBackend.
    """

    def __init__(self, config: PiConfig):
        self._config = config
        self._session_key = config.session_key
        self._project_dir = config.project_dir

        # Per-session state
        self._connected = False
        self._lock = asyncio.Lock()
        self._currently_sending: bool = False
        self._backend = PiBackend(config)

    @property
    def session_key(self) -> str:
        return self._session_key

    @property
    def connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # Project directory setup (forwarded to backend)
    # ------------------------------------------------------------------

    def ensure_project_dir(self) -> None:
        """Scaffold project directory, MCP config, and Claude settings.

        Delegates to the backend's ``setup()`` method.
        """
        self._backend.setup()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Connect if not already connected. Safe to call concurrently."""
        if self._connected:
            return
        async with self._lock:
            if self._connected:
                return

            logger.info(
                "Agent connecting (session=%s, cwd=%s)...",
                self._session_key,
                self._project_dir,
            )
            await self._backend.connect()
            self._connected = True
            logger.info("Agent connected (session=%s)", self._session_key)

    async def disconnect(self) -> None:
        """Disconnect and free resources. Safe to call concurrently."""
        async with self._lock:
            if self._connected:
                self._connected = False
                await self._backend.disconnect()
                logger.info("Agent disconnected (session=%s)", self._session_key)

    async def connect_eager(self) -> None:
        """Connect at startup. Logs but doesn't raise on failure."""
        try:
            await self.connect()
        except Exception:
            logger.warning(
                "Eager connect failed for %s -- will retry on first message", self._session_key, exc_info=True
            )

    async def shutdown(self) -> None:
        """Permanent shutdown -- disconnect."""
        await self.disconnect()

    async def reset(self) -> None:
        """Reset the agent session (new conversation, retains JSONL history)."""
        if self._connected:
            await self._backend.reset()

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    async def send(self, text: str) -> AsyncGenerator[str | None]:
        """Send a message and yield response chunks.

        Retries once on connection error if no chunks yielded yet.
        Yields None at tool-call boundaries.
        """
        yielded = False
        try:
            async for chunk in self._send_inner(text):
                yielded = True
                yield chunk
        except (RuntimeError, asyncio.TimeoutError, OSError) as exc:
            if yielded:
                logger.warning("Agent send failed mid-stream for %s (%s), not retrying", self._session_key, exc)
                return
            logger.warning("Agent send failed for %s (%s), reconnecting for retry", self._session_key, exc)
            await self.disconnect()
            async for chunk in self._send_inner(text):
                yield chunk

    async def _send_inner(self, text: str) -> AsyncGenerator[str | None]:
        """Core send logic -- delegates to backend."""
        self._currently_sending = True
        try:
            await self.connect()
            async for chunk in self._backend.send(text):
                yield chunk
        finally:
            self._currently_sending = False

    async def interrupt(self) -> None:
        """Interrupt the current query."""
        if self._connected:
            await self._backend.interrupt()
