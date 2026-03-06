"""WakeupManager — context-rich autonomous prompts for the Pi agent.

Builds situational prompts gathering time, weather, activity, memory
stats, and music context, then sends them to the agent. The agent
decides autonomously what to do based on the situation.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any

from ..core.context_helpers import (
    location_summary,
    now_playing_summary,
    weather_summary,
)

logger = logging.getLogger(__name__)

# Quiet hours: don't nudge before 7am or after 10pm local time
_QUIET_HOUR_START = 22  # 10pm
_QUIET_HOUR_END = 7  # 7am


class WakeupManager:
    """Builds situational prompts and sends them to the agent.

    Wire into the system:
    - ``bus.on("timer:fired", wakeup.on_timer_fired)``
    - ``scheduler.register("wakeup_pulse", wakeup.on_pulse, ...)``
    - ``scheduler.register("nudge", wakeup.on_nudge, ...)``
    """

    def __init__(
        self,
        agent: Any,
        state_store: Any = None,
        memory_service: Any = None,
        get_spotify_session: Any = None,
        accumulator: Any = None,
    ):
        self._agent = agent
        self._state = state_store
        self._memory = memory_service
        self._get_spotify_session = get_spotify_session
        self._accumulator = accumulator

    # ------------------------------------------------------------------
    # Trigger handlers
    # ------------------------------------------------------------------

    async def on_timer_fired(
        self, signal_name: str, *, name: str, label: str = "", wake_clarvis: bool = False, **kw
    ) -> None:
        """Handle timer:fired signal. Only wakes if wake_clarvis is set."""
        if wake_clarvis:
            await self._wakeup(reason="timer", timer_name=name, timer_label=label)

    async def on_pulse(self) -> None:
        """Regular check-in pulse from Scheduler."""
        await self._wakeup(reason="pulse")

    async def on_nudge(self) -> str | None:
        """Nudge with pending session context. Called by Scheduler.

        Guards: quiet hours, agent busy, no pending sessions.
        On success, clears the accumulator.
        """
        if self._is_quiet_hours():
            logger.debug("Nudge skipped: quiet hours")
            return None

        if getattr(self._agent, "_currently_sending", False):
            logger.debug("Nudge skipped: agent busy")
            return None

        sessions = self._get_pending_sessions()
        if not sessions:
            return None

        return await self._send_nudge(sessions)

    async def on_force_reflect(self) -> str | None:
        """Forced reflect nudge. Called by ``clarvis rem``.

        Bypasses quiet hours and agent-busy guards. Sends nudge with
        explicit reflect instruction.
        """
        sessions = self._get_pending_sessions()
        if sessions is None:
            logger.warning("Force reflect failed: accumulator not available")
            return None

        return await self._send_nudge(sessions, force_reflect=True)

    # ------------------------------------------------------------------
    # Core
    # ------------------------------------------------------------------

    async def _send_nudge(self, sessions: list[dict], force_reflect: bool = False) -> str | None:
        """Build nudge context from sessions and send to agent."""
        # Build session previews
        previews = []
        for sess in sessions[:5]:
            project = sess.get("project", "unknown")
            preview = sess.get("preview", "")[:1000]
            previews.append(f"  {project}:\n    {preview}")
        session_previews = "\n".join(previews)

        reason = "nudge — reflect" if force_reflect else "nudge"
        extra: dict[str, Any] = {
            "pending_sessions": len(sessions),
            "session_previews": session_previews,
        }
        if force_reflect:
            extra["force_reflect"] = True

        response = await self._wakeup(reason=reason, **extra)

        if response is not None:
            self._accumulator.mark_checked_in()

        return response

    async def _wakeup(self, reason: str, **context) -> str | None:
        """Build a context prompt and send to the agent.

        Returns the agent's response text, or None if no response.
        """
        # Gather now-playing in executor (sync Spotify call)
        np = None
        if self._get_spotify_session:
            loop = asyncio.get_running_loop()
            np = await loop.run_in_executor(None, now_playing_summary, self._get_spotify_session)
        # Fetch memory grounding (async)
        mem_ctx = None
        if self._memory:
            try:
                from clarvis.memory.ground import build_memory_context

                mem_ctx = await build_memory_context(self._memory, "master")
            except Exception:
                logger.debug("Wakeup memory grounding failed", exc_info=True)

        prompt = self._build_context_prompt(reason, now_playing=np, memory_context=mem_ctx, **context)
        logger.info("Wakeup (%s): sending prompt (%d chars)", reason, len(prompt))

        chunks: list[str] = []
        try:
            async for chunk in self._agent.send(prompt):
                if chunk is not None:
                    chunks.append(chunk)
        except Exception as e:
            logger.warning("Wakeup (%s) failed: %s", reason, e)
            return None

        response = "".join(chunks).strip() if chunks else None
        if response:
            logger.info("Wakeup response (%s): %s", reason, response[:200])
        return response

    def _build_context_prompt(self, reason: str, **context) -> str:
        """Assemble a situational prompt from available context sources."""
        local_time = datetime.now().astimezone().strftime("%A %H:%M")
        parts: list[str] = [
            f"[{reason}]",
            f"Time: {local_time}",
        ]

        # Weather + location
        ws = weather_summary(self._get_state("weather"))
        loc = location_summary(self._get_state("location"))
        if ws:
            weather_str = f"Weather: {ws}"
            if loc:
                weather_str += f" ({loc})"
            parts.append(weather_str)
        elif loc:
            parts.append(f"Location: {loc}")

        # Now playing (passed in from _wakeup)
        np = context.pop("now_playing", None)
        if np:
            parts.append(np)

        # Memory context (pre-fetched in _wakeup)
        mem_ctx = context.pop("memory_context", None)
        if mem_ctx:
            preview = mem_ctx[:300]
            if len(mem_ctx) > 300:
                preview += "..."
            parts.append(f"Memory snapshot: {preview}")

        # Reason-specific context
        if reason == "timer":
            name = context.get("timer_name", "?")
            label = context.get("timer_label", "")
            parts.append(f"Timer '{name}' fired" + (f": {label}" if label else ""))
        elif reason == "pulse":
            parts.append("Regular check-in. Review your memories, check if anything worth noting or acting on.")
        elif reason.startswith("nudge"):
            ps = context.get("pending_sessions", 0)
            previews = context.get("session_previews", "")
            if ps:
                parts.append(f"Pending sessions: {ps}")
            if previews:
                parts.append(f"Session transcripts:\n{previews}")
            if context.get("force_reflect"):
                parts.append("\nReflect requested. Run /reflect to process pending sessions and consolidate memories.")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_pending_sessions(self) -> list[dict] | None:
        """Return pending sessions from accumulator, or None if unavailable."""
        if not self._accumulator:
            return None
        pending = self._accumulator.get_pending()
        return pending.get("sessions_since_last", [])

    def _is_quiet_hours(self) -> bool:
        """Return True if current local time is in quiet hours (10pm-7am)."""
        hour = datetime.now().astimezone().hour
        return hour >= _QUIET_HOUR_START or hour < _QUIET_HOUR_END

    def _get_state(self, key: str) -> Any:
        """Safely get state from StateStore."""
        if not self._state:
            return None
        try:
            return self._state.get(key)
        except Exception:
            return None
