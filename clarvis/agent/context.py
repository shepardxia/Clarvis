"""Context injection for agent messages.

ContextInjector replaces ad-hoc grounding patterns across voice,
channels, nudge, and chat with a single class that layers memory
grounding (first turn only) and ambient context onto each message.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ContextInjector:
    """Enriches agent prompts with memory grounding and ambient context.

    Memory grounding is injected on the first turn of a session only.
    Ambient context (time, weather, now-playing) is included every turn
    when ``include_ambient`` is True.
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

    async def enrich(self, text: str, *, turn_prefix: str = "") -> str:
        """Build an enriched prompt with context layers.

        Layers (in order):
        1. Memory grounding (first turn of session only)
        2. Ambient context (every turn, if enabled)
        3. Turn-specific prefix (caller-supplied)
        4. User text
        """
        parts: list[str] = []

        # Layer 1: Memory grounding (first turn of session only)
        if not self._grounded and self._memory and self._memory.ready:
            try:
                from clarvis.memory.ground import build_memory_context

                ctx = await build_memory_context(self._memory, self._visibility)
                if ctx:
                    parts.append(ctx)
                    self._grounded = True
            except Exception:
                logger.debug("Memory grounding failed", exc_info=True)

        # Layer 2: Ambient context (every turn, if enabled)
        if self._include_ambient:
            from clarvis.core.context_helpers import build_ambient_context

            ambient = build_ambient_context(self._state)
            if ambient:
                parts.append(ambient)

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
