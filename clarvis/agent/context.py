"""Context injection for agent messages.

ContextInjector prepends ambient context (time, weather, now-playing)
to agent prompts.  Memory grounding is handled separately by
``Agent._inject_grounding()`` at session reset — not here.
"""

import logging
from typing import Any

from clarvis.core.context_helpers import build_ambient_context

logger = logging.getLogger(__name__)


class ContextInjector:
    """Enriches agent prompts with ambient context.

    Ambient context (time, weather, now-playing) is injected when the
    caller requests it via ``include_ambient=True``.

    Memory grounding is NOT handled here — see ``Agent._inject_grounding()``.
    """

    def __init__(
        self,
        state: Any,
        memory: Any | None,
        visibility: str,
    ):
        self._state = state
        self.memory = memory
        self.visibility = visibility

    async def enrich(
        self,
        text: str,
        *,
        turn_prefix: str = "",
        include_ambient: bool = False,
    ) -> str:
        """Build an enriched prompt with context layers.

        Layers (in order):
        1. Ambient context (when requested and enabled)
        2. Turn-specific prefix (caller-supplied)
        3. User text
        """
        parts: list[str] = []

        if include_ambient:
            ambient = build_ambient_context(self._state)
            if ambient:
                parts.append(ambient)

        if turn_prefix:
            parts.append(turn_prefix)

        if text:
            parts.append(text)

        return "\n\n".join(parts)
