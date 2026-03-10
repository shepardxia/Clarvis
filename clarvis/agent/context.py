"""Context injection for agent messages.

ContextInjector replaces ad-hoc grounding patterns across voice,
channels, nudge, and chat with a single class that layers memory
grounding (first turn only) and ambient context onto each message.
"""

import logging
import time
from typing import Any

from clarvis.core.context_helpers import build_ambient_context
from clarvis.memory.ground import build_memory_context

logger = logging.getLogger(__name__)

# Only inject ambient context if it's been this long since last injection.
AMBIENT_COOLDOWN_S = 3600  # 1 hour


class ContextInjector:
    """Enriches agent prompts with memory grounding and ambient context.

    Memory grounding is injected on the first turn of a session only.
    Ambient context (time, weather, now-playing) is included on the first
    turn and then again only after ``AMBIENT_COOLDOWN_S`` has elapsed,
    unless the caller forces it via ``include_ambient=True``.
    """

    def __init__(
        self,
        state: Any,
        memory: Any | None,
        visibility: str,
        include_ambient: bool = True,
    ):
        self._state = state
        self._memory = memory
        self._visibility = visibility
        self._include_ambient = include_ambient
        self._grounded = False
        self._last_ambient_ts: float = 0.0

    @property
    def memory(self) -> Any | None:
        return self._memory

    @property
    def visibility(self) -> str:
        return self._visibility

    def mark_grounded(self) -> None:
        self._grounded = True

    async def enrich(
        self,
        text: str,
        *,
        turn_prefix: str = "",
        include_ambient: bool | None = None,
    ) -> str:
        """Build an enriched prompt with context layers.

        Layers (in order):
        1. Memory grounding (first turn of session only)
        2. Ambient context (cooldown-gated; callers can override)
        3. Turn-specific prefix (caller-supplied)
        4. User text

        Args:
            include_ambient: Override ambient injection. ``True`` forces it
                (voice, nudge); ``None`` uses cooldown logic.
        """
        parts: list[str] = []

        # Layer 1: Memory grounding (first turn of session only)
        if not self._grounded and self._memory and self._memory.ready:
            try:
                ctx = await build_memory_context(self._memory, self._visibility)
                if ctx:
                    parts.append(ctx)
                # Mark grounded even if ctx is empty — avoid retrying every turn
                self._grounded = True
            except Exception:
                logger.debug("Memory grounding failed", exc_info=True)

        # Layer 2: Ambient context (cooldown-gated)
        if self._include_ambient:
            now = time.monotonic()
            if include_ambient is True:
                should_inject = True
            elif include_ambient is False:
                should_inject = False
            else:
                # Default: inject on first turn or after cooldown
                should_inject = self._last_ambient_ts == 0.0 or (now - self._last_ambient_ts) >= AMBIENT_COOLDOWN_S

            if should_inject:
                ambient = build_ambient_context(self._state)
                if ambient:
                    parts.append(ambient)
                    self._last_ambient_ts = now

        # Layer 3: Turn-specific prefix (caller-supplied)
        if turn_prefix:
            parts.append(turn_prefix)

        # Layer 4: User text
        if text:
            parts.append(text)

        return "\n\n".join(parts)

    def reset(self) -> None:
        """Reset grounding state for a new session."""
        self._grounded = False
