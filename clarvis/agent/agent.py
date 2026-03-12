"""Self-contained agent -- spawns ``pi --mode rpc`` as a subprocess.

Each channel (voice, Discord, etc.) gets its own Agent instance with
a fixed session key, its own Pi RPC process, and retry logic.
"""

import asyncio
import itertools
import json
import logging
import signal
import time
from collections.abc import AsyncGenerator
from contextlib import aclosing
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ..core.paths import STAGING_INBOX

if TYPE_CHECKING:
    from .context import ContextInjector

logger = logging.getLogger(__name__)


@dataclass
class AgentConfig:
    """Configuration for the Pi RPC agent."""

    session_key: str
    project_dir: Path
    model: str | None = None
    thinking: str | None = None


def auto_approve_extension_ui(agent: "Agent", event: dict) -> None:
    """Auto-respond to extension UI requests from Pi.

    Used by voice, channels, and nudge callers that run headless.
    Chat forwards these to the TUI instead.
    """
    ui_type = event.get("ui_type", "")
    if ui_type == "select":
        options = event.get("options", [])
        response = {"type": "extension_ui_response", "value": options[0] if options else ""}
    elif ui_type == "input":
        response = {"type": "extension_ui_response", "value": ""}
    else:
        # confirm / unknown -- approve
        response = {"type": "extension_ui_response", "value": True}

    req_id = event.get("id")
    if req_id:
        response["id"] = req_id
    agent._send_command(response)


async def collect_response(agent: "Agent", text: str, *, owner: str = "") -> str:
    """Send a message and collect the full text response.

    Auto-approves extension UI requests and returns the concatenated
    text deltas.  Used by channels and nudge — voice has its own
    streaming loop with interrupt/TTS handling.
    """
    from contextlib import aclosing

    chunks: list[str] = []
    async with aclosing(agent.send(text, owner=owner)) as stream:
        async for event in stream:
            etype = event.get("type")
            if etype == "extension_ui_request":
                auto_approve_extension_ui(agent, event)
            elif etype == "message_update":
                delta = event.get("assistantMessageEvent", {})
                if delta.get("type") == "text_delta":
                    chunks.append(delta.get("delta", ""))
            elif etype == "agent_end":
                break
    return "".join(chunks).strip()


class Agent:
    """Self-contained agent that drives ``pi --mode rpc`` as a subprocess.

    Spawns a Pi process with stdin/stdout JSON-lines RPC protocol.
    Background reader task pushes events to an asyncio queue consumed
    by ``send()``.
    """

    def __init__(self, config: AgentConfig):
        self._config = config
        self._session_key = config.session_key
        self._project_dir = config.project_dir
        self._model = config.model
        self._thinking = config.thinking
        self._session_file = config.project_dir / "pi-session.jsonl"

        self._connected = False
        self._lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()
        self._send_owner: str | None = None

        # ContextInjector -- set by daemon after construction
        self.context: "ContextInjector | None" = None

        # Subprocess state (initialized in connect)
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task | None = None
        self._reader_task: asyncio.Task | None = None
        self._events: asyncio.Queue = asyncio.Queue()
        self._counter = itertools.count(1)

    @property
    def session_key(self) -> str:
        return self._session_key

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def is_busy(self) -> bool:
        """True if the agent is currently processing a send."""
        return self._send_lock.locked()

    @property
    def send_owner(self) -> str | None:
        """Identifier of the caller currently holding the send lock."""
        return self._send_owner

    async def enrich(self, text: str, **kwargs) -> str:
        """Enrich text via ContextInjector if available, otherwise pass through."""
        if self.context:
            return await self.context.enrich(text, **kwargs)
        return text

    # ------------------------------------------------------------------
    # Project directory setup
    # ------------------------------------------------------------------

    def ensure_project_dir(self) -> None:
        """Create project directory if needed."""
        self._project_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Spawn Pi RPC subprocess if not already connected."""
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

            self.ensure_project_dir()

            cmd = ["pi", "--mode", "rpc", "--session", str(self._session_file)]
            if self._model:
                cmd.extend(["--model", self._model])
            if self._thinking:
                cmd.extend(["--thinking", self._thinking])

            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._project_dir),
                limit=1024 * 1024 * 1024,  # 1GB — Pi responses (get_messages) can be arbitrarily large
            )

            self._events = asyncio.Queue()
            self._counter = itertools.count(1)
            self._reader_task = asyncio.create_task(self._reader_loop())
            self._stderr_task = asyncio.create_task(self._forward_stderr())

            self._connected = True
            logger.info(
                "Agent connected (session=%s, pid=%s)",
                self._session_key,
                self._process.pid,
            )

    async def disconnect(self) -> None:
        """Shut down Pi process gracefully, then force-kill if needed."""
        async with self._lock:
            if not self._connected:
                return
            self._connected = False

            for task in (self._reader_task, self._stderr_task):
                if task and not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            self._reader_task = None
            self._stderr_task = None

            # Close stdin to signal graceful shutdown
            if self._process and self._process.stdin:
                try:
                    self._process.stdin.close()
                    await self._process.stdin.wait_closed()
                except Exception:
                    pass

            await self._kill_process(timeout=5.0)
            logger.info("Agent disconnected (session=%s)", self._session_key)

    async def connect_eager(self) -> None:
        """Connect at startup. Logs but doesn't raise on failure."""
        try:
            await self.connect()
        except Exception:
            logger.warning(
                "Eager connect failed for %s -- will retry on first message",
                self._session_key,
                exc_info=True,
            )

    async def shutdown(self) -> None:
        """Permanent shutdown -- disconnect."""
        await self.disconnect()

    async def reset(self) -> None:
        """Reset by moving session file to inbox and restarting Pi fresh."""
        was_connected = self._connected
        await self.disconnect()

        if self._session_file.exists():
            STAGING_INBOX.mkdir(parents=True, exist_ok=True)
            dest = STAGING_INBOX / f"session_{self._session_key}_{int(time.time())}.jsonl"
            self._session_file.rename(dest)
            logger.info("Moved session to %s", dest.name)

        if was_connected:
            await self.connect()
        if self.context:
            self.context.reset()

        await self._inject_grounding()

    async def _inject_grounding(self) -> None:
        """Send memory context as first message after session reset."""
        if not self.context or not self._connected:
            return

        from ..memory.ground import build_memory_context

        memory = self.context.memory
        visibility = self.context.visibility
        if not memory or not memory.ready:
            return

        try:
            ctx = await build_memory_context(memory, visibility)
            if not ctx:
                return

            async with aclosing(self.send(ctx, owner="grounding")) as stream:
                async for event in stream:
                    if event.get("type") == "agent_end":
                        break

            # Mark grounded so ContextInjector doesn't re-inject
            self.context.mark_grounded()
            logger.info("Injected memory grounding for %s", self._session_key)
        except Exception:
            logger.warning(
                "Failed to inject grounding for %s",
                self._session_key,
                exc_info=True,
            )

    async def reload(self) -> None:
        """Reload agent prompts, skills, and extensions.

        Pi has no reload RPC command -- restart the process with the same
        session file to pick up changes.
        """
        await self.disconnect()
        await self.connect()
        logger.info("Agent reloaded via restart (session=%s)", self._session_key)

    async def interrupt(self) -> None:
        """Interrupt the current query."""
        if not self._connected:
            return
        self._send_command({"type": "abort"})

    def steer(self, text: str) -> None:
        """Interrupt current run and redirect agent to new message."""
        self._send_command({"type": "steer", "message": text})

    def forward_ui_response(self, response: dict) -> None:
        """Forward an extension UI response to Pi."""
        self._send_command(response)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    async def send(self, text: str, *, owner: str = "") -> AsyncGenerator[dict]:
        """Send a message and yield raw Pi RPC event dicts.

        Callers filter events for what they need (text deltas, tool
        boundaries, extension UI, agent_end).

        Retries once on connection error if no events yielded yet.
        """
        yielded = False
        try:
            async for event in self._send_inner(text, owner=owner):
                yielded = True
                yield event
        except (RuntimeError, asyncio.TimeoutError, OSError) as exc:
            if yielded:
                logger.warning(
                    "Agent send failed mid-stream for %s (%s), not retrying",
                    self._session_key,
                    exc,
                )
                return
            logger.warning(
                "Agent send failed for %s (%s), reconnecting for retry",
                self._session_key,
                exc,
            )
            await self.disconnect()
            async for event in self._send_inner(text, owner=owner):
                yield event

    async def _send_inner(self, text: str, *, owner: str = "") -> AsyncGenerator[dict]:
        """Core send logic -- write prompt to stdin, yield raw events.

        Acquires the send lock internally so callers don't need to.
        """
        async with self._send_lock:
            self._send_owner = owner or None
            try:
                await self.connect()

                if not self._process or not self._process.stdin:
                    raise RuntimeError("Agent not connected")

                # Send prompt command
                req_id = f"req_{next(self._counter)}"
                cmd = {"type": "prompt", "message": text, "id": req_id}
                self._send_command(cmd)

                # Consume events until agent_end
                while True:
                    event = await self._events.get()
                    etype = event.get("type")

                    if etype == "_process_error":
                        raise RuntimeError(f"Process error: {event.get('error')}")

                    yield event

                    if etype == "agent_end":
                        return
            finally:
                self._send_owner = None

    async def command(self, cmd_type: str, **params) -> dict:
        """Send a non-prompt RPC command and wait for its response.

        Acquires the send lock, sends a command with a ``cmd_`` prefixed ID,
        and drains events until the matching ``{"type": "response"}`` arrives.
        Non-matching events are stashed and re-queued so ``send()`` can
        consume them later.

        Returns the ``data`` dict from the response.
        Raises RuntimeError on failure or timeout.
        """
        async with self._send_lock:
            self._send_owner = "command"
            try:
                await self.connect()

                if not self._process or not self._process.stdin:
                    raise RuntimeError("Agent not connected")

                req_id = f"cmd_{next(self._counter)}"
                cmd = {"type": cmd_type, "id": req_id, **params}
                self._send_command(cmd)

                stashed: list[dict] = []
                try:
                    while True:
                        event = await asyncio.wait_for(self._events.get(), timeout=10.0)
                        etype = event.get("type")

                        if etype == "_process_error":
                            raise RuntimeError(f"Process error: {event.get('error')}")

                        if etype == "response" and event.get("id") == req_id:
                            if not event.get("success", True):
                                raise RuntimeError(event.get("error", "Command failed"))
                            return event.get("data", {})

                        stashed.append(event)
                finally:
                    for ev in stashed:
                        await self._events.put(ev)
            finally:
                self._send_owner = None

    # ------------------------------------------------------------------
    # Background tasks
    # ------------------------------------------------------------------

    async def _reader_loop(self) -> None:
        """Background task: reads stdout JSON lines, pushes to event queue."""
        try:
            while self._process and self._process.stdout:
                line = await self._process.stdout.readline()
                if not line:
                    break

                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                await self._events.put(data)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Reader loop error")
        finally:
            await self._events.put({"type": "_process_error", "error": "Process connection lost"})

    async def _forward_stderr(self) -> None:
        """Forward Pi subprocess stderr to Python logger."""
        if not self._process or not self._process.stderr:
            return
        try:
            while True:
                line = await self._process.stderr.readline()
                if not line:
                    break
                msg = line.decode().rstrip()
                if msg:
                    logger.debug("[pi] %s", msg)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _send_command(self, cmd: dict) -> None:
        """Write a JSON-line command to Pi's stdin."""
        if not self._process or not self._process.stdin:
            raise RuntimeError("No process -- not connected")
        data = json.dumps(cmd) + "\n"
        self._process.stdin.write(data.encode())

    async def _kill_process(self, timeout: float = 5.0) -> None:
        """Terminate Pi process, escalating to SIGKILL if needed."""
        if not self._process:
            return
        try:
            self._process.send_signal(signal.SIGTERM)
            await asyncio.wait_for(self._process.wait(), timeout=timeout)
        except (asyncio.TimeoutError, ProcessLookupError):
            try:
                self._process.kill()
                await self._process.wait()
            except ProcessLookupError:
                pass
        self._process = None
