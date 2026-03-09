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
    """Reset Clarvis agent session (new_session RPC)."""
    import asyncio

    from ..paths import CLARVIS_HOME, agent_home

    # Flush unreflected session content to inbox before resetting
    session_reader = self._get_service("session_reader")
    if session_reader:
        inbox = CLARVIS_HOME / "staging" / "inbox"
        for source in ("clarvis", "factoria"):
            try:
                session_reader.flush_to_inbox(source, inbox)
            except Exception as exc:
                logger.warning("Failed to flush %s session to inbox: %s", source, exc)

    for sid_file in [
        agent_home("clarvis") / "session_id",
        agent_home("factoria") / "session_id",
    ]:
        sid_file.unlink(missing_ok=True)

    # Reset the Clarvis agent session
    agents = self._get_service("agents") or {}
    clarvis_agent = agents.get("clarvis")
    if clarvis_agent and clarvis_agent.connected:
        try:
            asyncio.run_coroutine_threadsafe(clarvis_agent.reset(), self.ctx.loop).result(timeout=30)
        except Exception as exc:
            logger.warning("Failed to reset Clarvis agent: %s", exc)

    # Disconnect voice orchestrator's agent if active
    orchestrator = self._get_service("voice")
    if orchestrator and orchestrator.agent.connected:
        asyncio.run_coroutine_threadsafe(orchestrator.agent.disconnect(), orchestrator._loop)

    return "ok"


def reflect_complete(self: CommandHandlers, **kw) -> dict:
    """Signal that reflect is done — advance watermarks and reset agents."""
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


def nudge_agent(self: CommandHandlers, *, reason: str = "timer", **kw) -> dict:
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


COMMANDS: dict[str, str] = {
    "reload_agents": "reload_agents",
    "reset_clarvis_session": "reset_clarvis_session",
    "reflect_complete": "reflect_complete",
    "listen": "listen",
    "nudge": "nudge_agent",
}
