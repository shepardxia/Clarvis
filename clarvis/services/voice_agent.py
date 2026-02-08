"""Voice agent — persistent Claude Code session for voice commands.

Wraps ClaudeSDKClient with lifecycle management: connect on demand,
disconnect on idle, resume previous conversation on reconnect.

Idle lifecycle is self-managed: after each send() completes, a 30-second
timer starts.  If no new send() arrives before it fires, the agent
auto-disconnects to free ~200 MB.  External callers only use
ensure_connected(), send(), and shutdown().
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)

logger = logging.getLogger(__name__)

VOICE_SYSTEM_PROMPT = """\
You are Clarvis, a voice assistant. You receive transcribed speech and respond conversationally.

Rules:
- Keep responses to 1-3 sentences unless asked for more.
- Act on commands directly — don't ask for clarification.
- Never use markdown formatting — your responses are spoken aloud via TTS.
- Use your tools for music control (Sonos/Spotify), weather, time, web search, and shell commands.
- For music: prefer search_and_play for simple requests, use batch for multi-step operations.
- A <context> block may precede the user's message with current situational data. \
Use it to inform your responses naturally — don't mention it explicitly.
- If a music_profile section is provided, use it to inform song/artist recommendations without being asked.
- If you need the user to answer a question before you can proceed, call the continue_listening tool. \
Do not generate additional text after calling continue_listening.\
"""

VOICE_ALLOWED_TOOLS = [
    "mcp__clarvis__*",
    "Bash",
    "WebSearch",
    "WebFetch",
]

MUSIC_PROFILE_PATH = Path.home() / ".claude/memories/music_profile_compact.md"

# Monorepo root: voice_agent.py → services/ → clarvis/ → Clarvis/ → clarvis-suite/
DEFAULT_PROJECT_DIR = Path(__file__).resolve().parents[3]

# Seconds of inactivity before the agent auto-disconnects to free memory.
IDLE_TIMEOUT = 30.0


class VoiceAgent:
    """Manages a persistent Claude Code session for voice commands.

    Lifecycle is self-managed via an idle timer:
    - send() cancels the idle timer on entry, restarts it in finally.
    - When the timer fires, the agent disconnects (~200 MB freed).
    - Next send() calls ensure_connected(), which reconnects with
      ``continue_conversation=True`` to resume the session — including
      across daemon restarts (sessions persist on disk).
    - shutdown() is called once at daemon exit to cancel the timer
      and disconnect immediately.
    """

    def __init__(
        self,
        event_loop: asyncio.AbstractEventLoop,
        project_dir: Path = DEFAULT_PROJECT_DIR,
        model: str | None = None,
        max_thinking_tokens: int | None = None,
    ):
        self._loop = event_loop
        self.project_dir = project_dir
        self._model = model
        self._max_thinking_tokens = max_thinking_tokens
        self._client: ClaudeSDKClient | None = None
        self._connected = False
        self._lock = asyncio.Lock()
        self._idle_handle: asyncio.TimerHandle | None = None
        self._sending = False  # True while send() is active (guards idle timer)
        self.expects_reply = False  # Set by send() when continue_listening tool detected

    # ------------------------------------------------------------------
    # Project directory setup
    # ------------------------------------------------------------------

    def ensure_project_dir(self) -> None:
        """Create the voice project directory with CLAUDE.md and .mcp.json if missing."""
        self.project_dir.mkdir(parents=True, exist_ok=True)

        claude_md = self.project_dir / "CLAUDE.md"
        if not claude_md.exists():
            claude_md.write_text(
                "# Clarvis Voice Assistant\n\n"
                "Voice-controlled assistant with access to music (Sonos/Spotify), "
                "weather, time, web search, and shell commands.\n"
            )

        mcp_json = self.project_dir / ".mcp.json"
        if not mcp_json.exists():
            mcp_json.write_text(json.dumps({"mcpServers": {}}, indent=2) + "\n")

    # ------------------------------------------------------------------
    # Agent options
    # ------------------------------------------------------------------

    def _build_options(self) -> ClaudeAgentOptions:
        # Build system prompt: base + music profile (if available)
        prompt = VOICE_SYSTEM_PROMPT
        try:
            profile = MUSIC_PROFILE_PATH.read_text().strip()
            if profile:
                prompt += f"\n\n{profile}"
        except (FileNotFoundError, OSError):
            pass

        mcp_path = self.project_dir / ".mcp.json"
        opts = ClaudeAgentOptions(
            cwd=str(self.project_dir),
            system_prompt=prompt,
            model=self._model,
            max_thinking_tokens=self._max_thinking_tokens,
            allowed_tools=VOICE_ALLOWED_TOOLS,
            permission_mode="bypassPermissions",
            setting_sources=["project"],
            continue_conversation=not os.environ.get("CLARVIS_NEW_CONVERSATION"),
        )
        if mcp_path.exists():
            opts.mcp_servers = str(mcp_path)
        return opts

    # ------------------------------------------------------------------
    # Idle timer
    # ------------------------------------------------------------------

    def _cancel_idle_timer(self) -> None:
        """Cancel the pending idle-disconnect timer, if any."""
        if self._idle_handle is not None:
            self._idle_handle.cancel()
            self._idle_handle = None

    def _start_idle_timer(self) -> None:
        """Schedule an idle-disconnect after IDLE_TIMEOUT seconds."""
        self._cancel_idle_timer()
        self._idle_handle = self._loop.call_later(IDLE_TIMEOUT, self._on_idle_timeout)

    def _on_idle_timeout(self) -> None:
        """Timer callback — schedule the async disconnect on the loop."""
        if self._sending:
            logger.debug("Idle timer fired during active send — rescheduling")
            self._start_idle_timer()
            return
        logger.info("Voice agent idle timeout — disconnecting")
        self._loop.create_task(self.disconnect())

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def ensure_connected(self) -> None:
        """Connect if not already connected. Safe to call concurrently."""
        self._cancel_idle_timer()
        if self._connected:
            return
        async with self._lock:
            # Double-check after acquiring lock
            if self._connected:
                return
            self.ensure_project_dir()

            opts = self._build_options()
            self._client = ClaudeSDKClient(opts)
            try:
                await asyncio.wait_for(self._client.connect(), timeout=10.0)
                self._connected = True
                logger.info("Voice agent connected")
            except (asyncio.TimeoutError, Exception) as e:
                logger.warning("Voice agent connect failed: %s", e)
                try:
                    await self._client.disconnect()
                except Exception:
                    pass
                self._client = None
                raise

    async def disconnect(self) -> None:
        """Disconnect and free resources (~200 MB). Safe to call concurrently."""
        async with self._lock:
            if self._client and self._connected:
                client = self._client
                self._connected = False
                self._client = None
                try:
                    await asyncio.wait_for(client.disconnect(), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning("Voice agent disconnect timed out after 5s")
                except Exception as e:
                    logger.debug("Voice agent disconnect cleanup: %s", e)
                logger.info("Voice agent disconnected")

    async def shutdown(self) -> None:
        """Permanent shutdown at daemon exit — cancel timer + disconnect."""
        self._cancel_idle_timer()
        await self.disconnect()

    @property
    def connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    async def send(self, text: str) -> AsyncIterator[str]:
        """Send a voice command and yield response text chunks.

        Manages the idle timer: cancels on entry, restarts in finally.
        Also detects continue_listening tool calls and sets
        self.expects_reply accordingly.  Text after the tool call
        is suppressed to prevent TTS from speaking it.
        """
        self._cancel_idle_timer()
        await self.ensure_connected()
        assert self._client is not None  # guaranteed by ensure_connected()

        self.expects_reply = False
        saw_signal = False

        self._sending = True
        try:
            await self._client.query(text)
            async for message in self._client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, ToolUseBlock) and "continue_listening" in block.name:
                            self.expects_reply = True
                            saw_signal = True
                            logger.debug("continue_listening tool detected")
                        elif isinstance(block, TextBlock) and not saw_signal:
                            yield block.text
                elif isinstance(message, ResultMessage):
                    return
        except Exception:
            logger.exception("Voice agent query failed, forcing disconnect")
            await self.disconnect()
            raise
        finally:
            self._sending = False
            self._start_idle_timer()

    async def interrupt(self) -> None:
        """Interrupt the current query (e.g. on cancellation)."""
        if self._client and self._connected:
            await self._client.interrupt()
