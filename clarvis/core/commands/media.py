"""Spotify and timer command handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import CommandHandlers


def spotify(self: CommandHandlers, *, command: str, **kw) -> str | dict:
    """Run a Spotify DSL command (e.g. 'play "jazz" volume 70')."""
    session = self._get_service("spotify_session")
    if session is None:
        return {"error": "Spotify not available"}
    try:
        return session.run(command)
    except Exception as e:
        return {"error": str(e)}


def timer(
    self: CommandHandlers,
    *,
    action: str,
    name: str | None = None,
    duration: str | None = None,
    at: str | None = None,
    label: str | None = None,
    recurring: bool = False,
    wake_clarvis: bool = False,
    **kw,
) -> str | dict:
    """Manage timers (set/list/cancel)."""
    svc = self._get_service("timer_service")
    if svc is None:
        return {"error": "Timer service not available"}

    if action == "set":
        if not name or (not duration and not at):
            return {"error": "set requires name and (duration or at)"}
        if duration and at:
            return {"error": "provide duration or at, not both"}
        from clarvis.services.timer_service import parse_duration, parse_time

        if at:
            try:
                at_seconds = parse_time(at)
            except ValueError as e:
                return {"error": str(e)}
            t = svc.set_timer(name, 0.0, recurring, label or "", wake_clarvis, at=at_seconds)
        else:
            try:
                seconds = parse_duration(duration)
            except ValueError as e:
                return {"error": str(e)}
            t = svc.set_timer(name, seconds, recurring, label or "", wake_clarvis)
        return f"Timer '{t.name}' set for {t.duration}s (fires at {t.fire_at})"
    elif action == "list":
        timers = svc.list_timers()
        if not timers:
            return "No active timers."
        lines = []
        for t in timers:
            t_name = t.get("name", t) if isinstance(t, dict) else str(t)
            lines.append(f"  - {t_name}")
        return "Active timers:\n" + "\n".join(lines)
    elif action == "cancel":
        if not name:
            return {"error": "cancel requires name"}
        ok = svc.cancel(name)
        return f"Cancelled timer '{name}'" if ok else f"Timer '{name}' not found"
    else:
        return {"error": f"Unknown action: {action}"}


COMMANDS: dict[str, str] = {
    "spotify": "spotify",
    "timer": "timer",
}
