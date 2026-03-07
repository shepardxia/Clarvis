"""Agent lifecycle command handlers — reload, reset, reflect, listen."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import CommandHandlers


def reload_agents(self: CommandHandlers, **kwargs) -> dict:
    """Reload agent prompts and context files (CLAUDE.md / AGENTS.md)."""
    import asyncio

    agents = self._get_service("agents") or {}
    if not agents:
        return {"error": "No agents initialized"}

    reloaded = []
    errors = []

    for name, agent in agents.items():
        backend = getattr(agent, "_backend", None)
        reload_fn = getattr(backend, "reload", None)
        if reload_fn is None:
            reloaded.append(f"{name}: skipped (no reload support)")
            continue
        try:
            asyncio.run_coroutine_threadsafe(reload_fn(), self.ctx.loop).result(timeout=15)
            reloaded.append(f"{name}: ok")
        except Exception as exc:
            errors.append(f"{name}: {exc}")

    return {"status": "ok", "reloaded": reloaded, "errors": errors}


def reset_clarvis_session(self: CommandHandlers, **kw) -> str:
    """Disconnect Clarvis agent so next interaction starts a fresh session."""
    import asyncio

    from ..paths import agent_home

    for sid_file in [
        agent_home("clarvis") / "session_id",
        agent_home("factoria") / "session_id",
    ]:
        sid_file.unlink(missing_ok=True)

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


COMMANDS: dict[str, str] = {
    "reload_agents": "reload_agents",
    "reset_clarvis_session": "reset_clarvis_session",
    "reflect_complete": "reflect_complete",
    "listen": "listen",
}
