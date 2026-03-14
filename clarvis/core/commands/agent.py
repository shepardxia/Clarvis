"""Agent lifecycle command handlers -- reload, reset, reflect, listen."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import CommandHandlers

logger = logging.getLogger(__name__)


def reload_agents(self: CommandHandlers, **kwargs) -> dict:
    """Reload agent prompts and context files (CLAUDE.md / AGENTS.md)."""
    import asyncio

    agents = self._get_service("agents") or {}
    if not agents:
        return {"error": "No agents initialized"}

    reloaded = []
    errors = []

    for name, agent in agents.items():
        try:
            asyncio.run_coroutine_threadsafe(agent.reload(), self.ctx.loop).result(timeout=15)
            reloaded.append(f"{name}: ok")
        except Exception as exc:
            errors.append(f"{name}: {exc}")

    return {"status": "ok", "reloaded": reloaded, "errors": errors}


def reset_clarvis_session(self: CommandHandlers, **kw) -> str:
    """Reset all agent sessions — moves session files to inbox and restarts."""
    import asyncio

    from ..paths import agent_home

    for sid_file in [
        agent_home("clarvis") / "session_id",
        agent_home("factoria") / "session_id",
    ]:
        sid_file.unlink(missing_ok=True)

    # Reset both agents in parallel (each handles its own file move + restart)
    agents = self._get_service("agents") or {}
    if agents:

        async def _reset_all():
            results = await asyncio.gather(
                *(a.reset() for a in agents.values()),
                return_exceptions=True,
            )
            for name, result in zip(agents, results):
                if isinstance(result, Exception):
                    logger.warning("Failed to reset %s agent: %s", name, result)

        asyncio.run_coroutine_threadsafe(_reset_all(), self.ctx.loop).result(timeout=30)

    return "ok"


def reflect_complete(self: CommandHandlers, **kw) -> dict:
    """Signal that reflect is done — archive inbox and reset agents."""
    import asyncio

    daemon = self._get_service("daemon")
    if not daemon:
        return {"error": "daemon not available"}
    try:
        result = asyncio.run_coroutine_threadsafe(daemon.complete_reflect(), self.ctx.loop).result(timeout=30)
        return result
    except Exception as exc:
        return {"error": str(exc)}


def listen(self: CommandHandlers, **kw) -> dict:
    """Signal the voice pipeline to start listening for a follow-up reply."""
    if self.ctx.bus is None:
        return {"error": "Voice pipeline not available"}
    self.ctx.bus.emit("voice:prompt_reply")
    return {"status": "listening"}


def nudge(self: CommandHandlers, *, reason: str = "timer", **kw) -> dict:
    """Send a context-rich nudge to the Clarvis agent."""
    import asyncio

    from ...services.wakeup import nudge

    agents = self._get_service("agents") or {}
    agent = agents.get("clarvis")
    if not agent:
        return {"error": "Clarvis agent not available"}

    try:
        response = asyncio.run_coroutine_threadsafe(
            nudge(agent, reason, **kw),
            self.ctx.loop,
        ).result(timeout=120)
        return {"status": "ok", "response": response}
    except Exception as exc:
        return {"error": str(exc)}


def read_sessions(self: CommandHandlers, *, path: str, **kw) -> dict:
    """Parse a Pi session JSONL file and return structured messages."""
    from pathlib import Path

    from ...memory.session_reader import parse_session

    messages = parse_session(Path(path))
    return {"messages": messages, "count": len(messages)}


def speak(self: CommandHandlers, *, text: str, **kw) -> dict:
    """Speak text aloud. Uses voice pipeline if available, raw say otherwise."""
    import asyncio

    orchestrator = self._get_service("voice")
    if orchestrator:
        future = asyncio.run_coroutine_threadsafe(
            orchestrator.speak(text),
            self.ctx.loop,
        )

        def _on_done(f):
            exc = f.exception()
            if exc:
                logger.error("orchestrator.speak() failed: %s", exc, exc_info=exc)

        future.add_done_callback(_on_done)
        return {"status": "ok"}

    # Fallback: raw macOS say (no voice pipeline configured)
    voice_cfg = self.ctx.config.voice

    async def _say() -> None:
        proc = await asyncio.create_subprocess_exec(
            "say",
            "-v",
            voice_cfg.tts_voice,
            "-r",
            str(voice_cfg.tts_speed),
            text,
        )
        await proc.wait()

    asyncio.run_coroutine_threadsafe(_say(), self.ctx.loop)
    return {"status": "ok"}


COMMANDS: list[str] = [
    "reload_agents",
    "reset_clarvis_session",
    "reflect_complete",
    "listen",
    "nudge",
    "read_sessions",
    "speak",
]
