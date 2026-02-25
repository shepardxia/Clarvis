"""WakeupManager — context-rich autonomous prompts for the Pi agent.

Builds situational prompts gathering time, weather, activity, memory
stats, and music context, then sends them to the agent. The agent
decides autonomously what to do based on the situation.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from ..core.context_helpers import (
    location_summary,
    now_playing_summary,
    weather_summary,
)

logger = logging.getLogger(__name__)


class WakeupManager:
    """Builds situational prompts and sends them to the agent.

    Wire into the system:
    - ``bus.on("timer:fired", wakeup.on_timer_fired)``
    - ``scheduler.register("wakeup_pulse", wakeup.on_pulse, ...)``
    """

    def __init__(
        self,
        agent: Any,
        state_store: Any = None,
        memory_service: Any = None,
        consolidator: Any = None,
        get_spotify_session: Any = None,
    ):
        self._agent = agent
        self._state = state_store
        self._memory = memory_service
        self._consolidator = consolidator
        self._get_spotify_session = get_spotify_session

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

    async def on_consolidation_needed(self, session_key: str) -> None:
        """Triggered when conversation needs memory consolidation."""
        await self._wakeup(reason="consolidation", session_key=session_key)

    # ------------------------------------------------------------------
    # Core
    # ------------------------------------------------------------------

    async def _wakeup(self, reason: str, **context) -> str | None:
        """Build a context prompt and send to the agent.

        Returns the agent's response text, or None if no response.
        """
        # Gather now-playing in executor (sync Spotify call)
        np = None
        if self._get_spotify_session:
            loop = asyncio.get_running_loop()
            np = await loop.run_in_executor(None, now_playing_summary, self._get_spotify_session)
        prompt = self._build_context_prompt(reason, now_playing=np, **context)
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
        now = datetime.now(timezone.utc)
        parts: list[str] = [
            f"[Wakeup — {reason}]",
            f"Time: {now.strftime('%Y-%m-%d %H:%M UTC')}",
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

        # Memory context
        if self._consolidator:
            mem_ctx = self._consolidator.get_memory_context()
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
        elif reason == "consolidation":
            sk = context.get("session_key", "?")
            parts.append(f"Session '{sk}' needs memory consolidation")
        elif reason == "pulse":
            parts.append(
                "Regular check-in. Review your memories, check if anything worth noting or acting on. Tend the garden."
            )

        parts.append(
            "\nYou're waking up. Assess the situation and do what feels right — "
            "garden memories, check timers, observe, or just rest."
        )
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_state(self, key: str) -> Any:
        """Safely get state from StateStore."""
        if not self._state:
            return None
        try:
            return self._state.get(key)
        except Exception:
            return None
