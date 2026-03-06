"""Pi-coding-agent backend — drives a Node.js bridge subprocess.

The bridge wraps ``createAgentSession()`` from ``@mariozechner/pi-coding-agent``
and communicates via JSON-lines over a Unix socket.  Each agent instance
(Clarvis, Factoria) gets its own bridge process.
"""

import asyncio
import json
import logging
import os
import signal
from collections.abc import AsyncGenerator
from pathlib import Path

from .protocol import BackendConfig

logger = logging.getLogger(__name__)

# Resolve pi-bridge relative to this file:
#   backends/ → agent/ → pi-bridge/
_BRIDGE_DIR = Path(__file__).resolve().parents[1] / "pi-bridge"


def _subprocess_env() -> dict[str, str]:
    """Snapshot os.environ for subprocess use (already loaded by core.env)."""
    return dict(os.environ)


class PiBackend:
    """Backend that drives a pi-coding-agent bridge subprocess."""

    def __init__(self, config: BackendConfig):
        self._config = config
        self._process: asyncio.subprocess.Process | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._stderr_task: asyncio.Task | None = None
        self._connected = False
        self._socket_path = f"/tmp/clarvis-pi-{config.session_key}.sock"
        self._session_file = config.project_dir / "pi-session.jsonl"

    # ── Protocol properties ──

    @property
    def connected(self) -> bool:
        return self._connected

    # ── Lifecycle ──

    def setup(self) -> None:
        """Create project directory if needed."""
        self._config.project_dir.mkdir(parents=True, exist_ok=True)

    async def connect(self) -> None:
        """Spawn bridge subprocess and connect via Unix socket."""
        if self._connected:
            return

        self.setup()

        # Build env for the bridge process
        env = _subprocess_env()
        env["PI_BRIDGE_SOCKET"] = self._socket_path
        env["PI_BRIDGE_CWD"] = str(self._config.project_dir)
        env["PI_BRIDGE_SESSION_FILE"] = str(self._session_file)

        if self._config.mcp_port:
            env["PI_BRIDGE_MCP_PORT"] = str(self._config.mcp_port)
        if self._config.model:
            env["PI_BRIDGE_MODEL"] = self._config.model
        # Read thinking level from PiConfig via widget config
        try:
            from ...display.config import get_config

            thinking = get_config().channels.pi.thinking_level
            env["PI_BRIDGE_THINKING"] = thinking
        except Exception:
            pass

        bridge_js = _BRIDGE_DIR / "dist" / "bridge.js"
        if not bridge_js.exists():
            raise FileNotFoundError(f"Pi bridge not built: {bridge_js} — run 'npm run build' in {_BRIDGE_DIR}")

        # Clean up stale socket
        sock_path = Path(self._socket_path)
        if sock_path.exists():
            sock_path.unlink()

        # Spawn bridge
        self._process = await asyncio.create_subprocess_exec(
            "node",
            str(bridge_js),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        # Wait for READY on stdout (bridge prints "READY\n" once session is created)
        try:
            ready_line = await asyncio.wait_for(self._process.stdout.readline(), timeout=60.0)
            if b"READY" not in ready_line:
                raise RuntimeError(f"Bridge did not signal READY, got: {ready_line!r}")
        except asyncio.TimeoutError:
            await self._kill_process()
            raise RuntimeError("Bridge startup timed out (60s)")

        # Start forwarding stderr to logger
        self._stderr_task = asyncio.create_task(self._forward_stderr())

        # Connect Unix socket
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_unix_connection(self._socket_path),
                timeout=5.0,
            )
        except (asyncio.TimeoutError, OSError) as e:
            await self._kill_process()
            raise RuntimeError(f"Failed to connect to bridge socket: {e}")

        self._connected = True
        logger.info(
            "PiBackend connected (session=%s, pid=%s)",
            self._config.session_key,
            self._process.pid,
        )

    async def disconnect(self) -> None:
        """Shut down bridge gracefully, then force-kill if needed."""
        if not self._connected:
            return

        # Cancel stderr forwarder
        if self._stderr_task and not self._stderr_task.done():
            self._stderr_task.cancel()
        self._stderr_task = None

        # Try graceful shutdown
        try:
            self._send_command({"method": "shutdown"})
        except Exception:
            pass

        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None

        await self._kill_process(timeout=5.0)
        self._connected = False
        logger.info("PiBackend disconnected (session=%s)", self._config.session_key)

    # ── Messaging ──

    async def send(self, text: str) -> AsyncGenerator[str | None, None]:
        """Send a prompt and yield text chunks / None at tool boundaries."""
        if not self._connected or not self._writer or not self._reader:
            raise RuntimeError("PiBackend not connected")

        self._send_command({"method": "prompt", "params": {"text": text}})

        while True:
            line = await self._reader.readline()
            if not line:
                raise RuntimeError("Bridge connection lost")

            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            etype = event.get("event")
            if etype == "text_delta":
                yield event.get("text", "")
            elif etype == "tool_end":
                yield None
            elif etype == "agent_end":
                return
            elif etype == "error":
                raise RuntimeError(f"Bridge error: {event.get('message')}")

    async def interrupt(self) -> None:
        """Send abort command to the bridge."""
        if self._connected and self._writer:
            try:
                self._send_command({"method": "abort"})
            except Exception:
                pass

    async def reload(self) -> None:
        """Reload agent prompts, skills, and extensions."""
        if not self._connected or not self._writer or not self._reader:
            raise RuntimeError("PiBackend not connected")

        self._send_command({"method": "reload"})

        # Wait for reload_done or error
        while True:
            line = await asyncio.wait_for(self._reader.readline(), timeout=10.0)
            if not line:
                raise RuntimeError("Bridge connection lost during reload")
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("event") == "reload_done":
                logger.info("PiBackend reloaded (session=%s)", self._config.session_key)
                return
            if event.get("event") == "error":
                raise RuntimeError(f"Reload failed: {event.get('message')}")

    # ── Session ID (no-op — managed by bridge's SessionManager) ──

    def set_session_id(self, sid: str | None) -> None:
        pass

    def get_session_id(self) -> str | None:
        return None

    # ── Internal helpers ──

    def _send_command(self, cmd: dict) -> None:
        """Write a JSON-line command to the bridge socket."""
        if not self._writer:
            raise RuntimeError("No writer — not connected")
        data = json.dumps(cmd) + "\n"
        self._writer.write(data.encode())

    async def _forward_stderr(self) -> None:
        """Forward bridge stderr to Python logger."""
        if not self._process or not self._process.stderr:
            return
        while True:
            line = await self._process.stderr.readline()
            if not line:
                break
            msg = line.decode().rstrip()
            if "[bridge]" in msg:
                logger.info("[pi-bridge] %s", msg)
            else:
                logger.debug("[pi-bridge] %s", msg)

    async def _kill_process(self, timeout: float = 5.0) -> None:
        """Terminate bridge process, escalating to SIGKILL if needed."""
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
