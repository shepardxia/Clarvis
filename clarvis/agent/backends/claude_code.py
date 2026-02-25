"""Claude Code SDK backend -- wraps ClaudeSDKClient.

Extracted from Agent to isolate SDK-specific concerns behind the
AgentBackend protocol.  Agent delegates connect/disconnect/send/interrupt
to this class while keeping retry logic and session-ID persistence.
"""

import asyncio
import json
import logging
import os
import signal
from collections.abc import AsyncGenerator
from typing import Any

from .protocol import BackendConfig

logger = logging.getLogger(__name__)

_UNSET = object()


def _sdk():
    """Lazy import of claude_agent_sdk."""
    import claude_agent_sdk

    return claude_agent_sdk


class ClaudeCodeBackend:
    """Backend that drives the Claude Code CLI via its Python SDK."""

    def __init__(self, config: BackendConfig, force_new: bool = False):
        self._config = config
        self._force_new = force_new
        self._fresh_attempted = False
        self._client: Any = None
        self._connected = False
        self._cli_pid: int | None = None
        self._project_dir_ready = False
        self._identity_prompt: str | None = _UNSET
        self._last_session_id: str | None = None

    # ------------------------------------------------------------------
    # AgentBackend protocol
    # ------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._connected

    def setup(self) -> None:
        """One-time project directory scaffolding."""
        self._ensure_project_dir()

    async def connect(self) -> None:
        """Establish SDK connection to the Claude Code CLI."""
        if self._connected:
            return
        self.setup()
        opts = self._build_options()
        sdk = _sdk()
        self._client = sdk.ClaudeSDKClient(opts)
        t0 = asyncio.get_running_loop().time()
        try:
            await asyncio.wait_for(self._client.connect(), timeout=30.0)
            self._connected = True
            try:
                self._cli_pid = self._client._transport._process.pid
            except (AttributeError, TypeError):
                self._cli_pid = None
            elapsed = asyncio.get_running_loop().time() - t0
            logger.info(
                "ClaudeCodeBackend connected (session=%s, pid=%s) in %.1fs",
                self._config.session_key,
                self._cli_pid,
                elapsed,
            )
        except (asyncio.TimeoutError, Exception) as e:
            elapsed = asyncio.get_running_loop().time() - t0
            logger.warning(
                "ClaudeCodeBackend connect failed for %s after %.1fs: %s: %s",
                self._config.session_key,
                elapsed,
                type(e).__name__,
                e,
            )
            try:
                await self._client.disconnect()
            except Exception:
                pass
            self._client = None
            raise

    async def disconnect(self) -> None:
        """Disconnect from CLI, force-killing if graceful timeout expires."""
        if self._client and self._connected:
            client = self._client
            pid = self._cli_pid
            self._connected = False
            self._client = None
            self._cli_pid = None
            try:
                await asyncio.wait_for(client.disconnect(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning(
                    "ClaudeCodeBackend disconnect timed out -- force-killing pid %s",
                    pid,
                )
                self._force_kill(pid)
            except Exception as e:
                logger.debug("ClaudeCodeBackend disconnect cleanup: %s", e)
            logger.info(
                "ClaudeCodeBackend disconnected (session=%s)",
                self._config.session_key,
            )

    async def send(self, text: str) -> AsyncGenerator[str | None, None]:
        """Send a message and yield response chunks.

        Yields text chunks and ``None`` at tool-call boundaries.
        Captures session ID from ``ResultMessage``.
        No retry -- the owning Agent handles that.
        """
        await self.connect()
        assert self._client is not None

        sdk = _sdk()
        try:
            await self._client.query(text)
            async for message in self._client.receive_response():
                if isinstance(message, sdk.AssistantMessage):
                    has_tool = False
                    for block in message.content:
                        if isinstance(block, sdk.ToolUseBlock):
                            has_tool = True
                        elif isinstance(block, sdk.TextBlock):
                            yield block.text
                    if has_tool:
                        yield None
                elif isinstance(message, sdk.ResultMessage):
                    if message.session_id and message.session_id != self._last_session_id:
                        self._last_session_id = message.session_id
                    return
        except (sdk.CLIConnectionError, sdk.ProcessError):
            await self.disconnect()
            raise
        except Exception:
            logger.exception(
                "ClaudeCodeBackend query failed for %s, forcing disconnect",
                self._config.session_key,
            )
            await self.disconnect()
            raise

    async def interrupt(self) -> None:
        """Interrupt the current query."""
        if self._client and self._connected:
            await self._client.interrupt()

    # ------------------------------------------------------------------
    # Drain (SDK-specific -- not part of AgentBackend protocol)
    # ------------------------------------------------------------------

    async def drain(self) -> AsyncGenerator[str | None, None]:
        """Drain buffered messages without issuing a new query.

        Used after interrupt() to consume leftover AssistantMessage /
        ResultMessage chunks before the next query() call.
        """
        if not self._client or not self._connected:
            return

        sdk = _sdk()
        try:
            async for message in self._client.receive_response():
                if isinstance(message, sdk.AssistantMessage):
                    has_tool = False
                    for block in message.content:
                        if isinstance(block, sdk.ToolUseBlock):
                            has_tool = True
                        elif isinstance(block, sdk.TextBlock):
                            yield block.text
                    if has_tool:
                        yield None
                elif isinstance(message, sdk.ResultMessage):
                    if message.session_id and message.session_id != self._last_session_id:
                        self._last_session_id = message.session_id
                    return
        except Exception:
            logger.debug("drain() error for %s", self._config.session_key, exc_info=True)

    # ------------------------------------------------------------------
    # Session ID bridge (Agent persists to file, backend holds in-memory)
    # ------------------------------------------------------------------

    def set_session_id(self, sid: str | None) -> None:
        self._last_session_id = sid

    def get_session_id(self) -> str | None:
        return self._last_session_id

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_project_dir(self) -> None:
        """Scaffold project directory, MCP config, and Claude settings.

        Only handles infrastructure (directory + git init + MCP config +
        settings).  Does NOT write ``CLAUDE.md`` -- persona content is a
        caller concern because each channel has a different identity.
        ``.mcp.json`` and ``.claude/settings.local.json`` are always
        overwritten so the port and approvals stay in sync.

        Cached after first successful call -- safe to call repeatedly.
        """
        if self._project_dir_ready:
            return

        project_dir = self._config.project_dir
        project_dir.mkdir(parents=True, exist_ok=True)

        # Claude Code CLI requires a git repo to function.
        git_dir = project_dir / ".git"
        if not git_dir.exists():
            import subprocess

            subprocess.run(
                ["git", "init"],
                cwd=project_dir,
                capture_output=True,
            )

        mcp_json = project_dir / ".mcp.json"
        if self._config.mcp_port is not None:
            # Merge clarvis entry into existing .mcp.json (preserves other servers)
            existing = {}
            if mcp_json.exists():
                try:
                    existing = json.loads(mcp_json.read_text())
                except (json.JSONDecodeError, OSError):
                    pass
            servers = existing.get("mcpServers", {})
            servers["clarvis"] = {
                "type": "http",
                "url": f"http://127.0.0.1:{self._config.mcp_port}/mcp",
            }
            existing["mcpServers"] = servers
            mcp_json.write_text(json.dumps(existing, indent=2) + "\n")
        elif not mcp_json.exists():
            mcp_json.write_text(json.dumps({"mcpServers": {}}, indent=2) + "\n")

        # Pre-approve MCP servers and disable plugins so headless agents
        # don't hang waiting for interactive approval that never comes.
        claude_dir = project_dir / ".claude"
        claude_dir.mkdir(exist_ok=True)

        settings_local = claude_dir / "settings.local.json"
        # Merge -- ensure "clarvis" is approved without clobbering other servers
        existing_local = {}
        if settings_local.exists():
            try:
                existing_local = json.loads(settings_local.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        existing_local.setdefault("permissions", {"allow": []})
        existing_local["enableAllProjectMcpServers"] = True
        approved = existing_local.get("enabledMcpjsonServers", [])
        if "clarvis" not in approved:
            approved.append("clarvis")
        existing_local["enabledMcpjsonServers"] = approved
        settings_local.write_text(json.dumps(existing_local, indent=2) + "\n")

        settings_json = claude_dir / "settings.json"
        if not settings_json.exists():
            settings_json.write_text(json.dumps({"enabledPlugins": {}}, indent=2) + "\n")

        self._project_dir_ready = True

    def _load_identity(self) -> str | None:
        """Read CLAUDE.md from project dir to use as agent system prompt.

        Cached after first load -- CLAUDE.md is static for the agent's lifetime.
        """
        if self._identity_prompt is not _UNSET:
            return self._identity_prompt
        claude_md = self._config.project_dir / "CLAUDE.md"
        try:
            content = claude_md.read_text().strip()
            self._identity_prompt = content or None
        except (FileNotFoundError, OSError):
            self._identity_prompt = None
        return self._identity_prompt

    def _on_stderr(self, line: str) -> None:
        """Capture CLI stderr to debug log instead of raw ANSI on stderr."""
        logger.debug("[%s:stderr] %s", self._config.session_key, line.rstrip())

    def _build_options(self):
        sdk = _sdk()
        opts = sdk.ClaudeAgentOptions(
            cwd=str(self._config.project_dir),
            model=self._config.model,
            max_thinking_tokens=self._config.max_thinking_tokens,
            allowed_tools=self._config.allowed_tools,
            permission_mode="bypassPermissions",
            # "project" only -- skip user settings (~/.claude.json) to avoid
            # trust dialogs, stale MCP servers, and other interactive prompts
            # that block headless agents.
            setting_sources=["project"],
            system_prompt=self._config.system_prompt or self._load_identity(),
            stderr=self._on_stderr,
            # Unset ANTHROPIC_API_KEY so the bundled CLI uses OAuth subscription
            # auth instead of the API platform (daemon has it for memory services).
            env={"ANTHROPIC_API_KEY": ""},
        )

        if self._force_new and not self._fresh_attempted:
            self._fresh_attempted = True
            # Start completely fresh -- neither resume nor continue
        else:
            # In-memory ID (hot path), fall back to file (cold start after restart)
            if self._last_session_id:
                opts.resume = self._last_session_id
            else:
                opts.continue_conversation = True

        # .mcp.json is auto-discovered from cwd -- no need for --mcp-config
        return opts

    @staticmethod
    def _force_kill(pid: int | None) -> None:
        """SIGKILL a CLI subprocess if it's still alive."""
        if pid is None:
            return
        try:
            os.kill(pid, signal.SIGKILL)
            logger.info("Force-killed orphaned CLI subprocess (pid=%d)", pid)
        except ProcessLookupError:
            pass  # already dead
        except OSError as e:
            logger.debug("Failed to force-kill pid %d: %s", pid, e)
