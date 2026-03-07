"""Nudge — context-rich autonomous prompts for the Pi agent.

Builds situational prompts gathering time, weather, and music context,
then sends them to the agent. The agent decides autonomously what to do
based on the situation.
"""

import logging
from typing import Any

from ..core.context_helpers import build_ambient_context

logger = logging.getLogger(__name__)


async def nudge(
    agent: Any,
    reason: str,
    state_store: Any = None,
    **context,
) -> str | None:
    """Send a context-rich prompt to the agent. Returns response text or None."""
    prompt = _build_prompt(reason, state_store, **context)
    logger.info("Nudge (%s): sending prompt (%d chars)", reason, len(prompt))

    chunks: list[str] = []
    try:
        async for chunk in agent.send(prompt):
            if chunk is not None:
                chunks.append(chunk)
    except Exception as e:
        logger.warning("Nudge (%s) failed: %s", reason, e)
        return None

    response = "".join(chunks).strip() if chunks else None
    if response:
        logger.info("Nudge response (%s): %s", reason, response[:200])
    return response


def _build_prompt(reason: str, state_store: Any, **context) -> str:
    """Minimal situational context for nudge."""
    parts: list[str] = [f"[{reason}]"]
    parts.append(build_ambient_context(state_store))

    # Reason-specific context
    if reason == "timer":
        name = context.get("timer_name", "?")
        label = context.get("timer_label", "")
        parts.append(f"Timer '{name}' fired" + (f": {label}" if label else ""))
    elif reason == "reflect":
        parts.append("Reflect requested. Run /reflect to process pending sessions and consolidate memories.")

    return "\n".join(parts)
