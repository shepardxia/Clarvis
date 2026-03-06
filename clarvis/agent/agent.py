"""Self-contained Claude Code agent -- owns session, profile, SDK client, lifecycle.

Each channel (voice, Discord, etc.) gets its own Agent instance with
a fixed session key, its own SDK connection, and retry logic.

The Agent delegates SDK-specific concerns to an ``AgentBackend``
(default: ``ClaudeCodeBackend``).  It retains retry logic, session-ID
persistence, and the concurrency lock.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


def _sdk():
    """Lazy import of claude_agent_sdk (for exception types only)."""
    import claude_agent_sdk

    return claude_agent_sdk


AGENT_ALLOWED_TOOLS = [
    "mcp__clarvis__*",
    "Bash",
    "WebSearch",
    "WebFetch",
]


@dataclass
class SessionProfile:
    """Per-channel isolation: separate project dir, session ID, tools, and MCP port."""

    project_dir: Path
    session_id_path: Path  # e.g. project_dir / "session_id"
    allowed_tools: list[str]
    mcp_port: int | None = None  # which MCP port this session's .mcp.json points to


class Agent:
    """Self-contained Claude Code agent with full lifecycle management.

    Each channel (voice, Discord, etc.) gets its own Agent with a fixed
    session key.  The agent delegates to a backend for SDK/CLI concerns
    while owning retry logic and session-ID persistence.
    """

    def __init__(
        self,
        session_key: str,
        profile: SessionProfile,
        event_loop: asyncio.AbstractEventLoop,
        backend=None,  # AgentBackend (duck-typed via Protocol)
        model: str | None = None,
        max_thinking_tokens: int | None = None,
        force_new: bool = False,
    ):
        self._session_key = session_key
        self._profile = profile
        self._loop = event_loop

        # Per-session state
        self._connected = False
        self._lock = asyncio.Lock()
        self._currently_sending: bool = False
        self._last_session_id: str | None = None

        # Build backend if not injected
        if backend is not None:
            self._backend = backend
        else:
            from .backends.claude_code import ClaudeCodeBackend
            from .backends.protocol import BackendConfig

            config = BackendConfig(
                session_key=session_key,
                project_dir=profile.project_dir,
                session_id_path=profile.session_id_path,
                model=model,
                max_thinking_tokens=max_thinking_tokens,
                mcp_port=profile.mcp_port,
                allowed_tools=profile.allowed_tools,
            )
            self._backend = ClaudeCodeBackend(config, force_new=force_new)

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
    # Session ID persistence
    # ------------------------------------------------------------------

    def _read_session_id(self) -> str | None:
        """Read session ID from the profile's file."""
        path = self._profile.session_id_path
        try:
            return path.read_text().strip() or None
        except (FileNotFoundError, OSError):
            return None

    def _write_session_id(self, session_id: str) -> None:
        """Write session ID to the profile's session_id file."""
        path = self._profile.session_id_path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(session_id)
        except OSError:
            logger.warning("Failed to write session ID file for %s", self._session_key)

    def _clear_session_id(self) -> None:
        """Remove saved session ID so retry starts fresh."""
        path = self._profile.session_id_path
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

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

            # Sync session ID from file to backend before connecting
            session_id = self._last_session_id or self._read_session_id()
            if session_id:
                self._backend.set_session_id(session_id)

            logger.info(
                "Agent connecting (session=%s, cwd=%s)...",
                self._session_key,
                self._profile.project_dir,
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

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    async def send(self, text: str) -> AsyncGenerator[str | None]:
        """Send a message and yield response chunks.

        Retries once on connection error if no chunks yielded yet.
        Only clears session on hard crash (ProcessError) -- transient
        timeouts preserve the conversation so retry can resume.
        Yields None at tool-call boundaries.
        """
        yielded = False
        try:
            async for chunk in self._send_inner(text):
                yielded = True
                yield chunk
        except (_sdk().CLIConnectionError, _sdk().ProcessError, asyncio.TimeoutError) as exc:
            if yielded:
                logger.warning("Agent send failed mid-stream for %s (%s), not retrying", self._session_key, exc)
                return
            logger.warning("Agent send failed for %s (%s), reconnecting for retry", self._session_key, exc)
            # Only wipe session for hard crashes -- keep it for transient errors
            if isinstance(exc, _sdk().ProcessError):
                self._last_session_id = None
                self._backend.set_session_id(None)
                self._clear_session_id()
            await self.disconnect()
            async for chunk in self._send_inner(text):
                yield chunk

    async def _send_inner(self, text: str) -> AsyncGenerator[str | None]:
        """Core send logic -- delegates to backend, syncs session ID back."""
        self._currently_sending = True
        try:
            await self.connect()
            async for chunk in self._backend.send(text):
                yield chunk
            # Sync session ID back from backend
            new_id = self._backend.get_session_id()
            if new_id and new_id != self._last_session_id:
                self._last_session_id = new_id
                self._write_session_id(new_id)
        finally:
            self._currently_sending = False

    async def interrupt(self) -> None:
        """Interrupt the current query."""
        if self._connected:
            await self._backend.interrupt()
