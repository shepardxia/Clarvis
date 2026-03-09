"""Nudge -- context-rich autonomous prompts for the Pi agent.

Builds situational prompts gathering time, weather, and music context,
then sends them to the agent. The agent decides autonomously what to do
based on the situation.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def nudge(
    agent: Any,
    reason: str,
    **context,
) -> str | None:
    """Send a context-rich prompt to the agent. Returns response text or None."""
    from ..agent.agent import collect_response

    # Skip if agent is busy with voice (voice has priority)
    if agent.is_busy:
        owner = agent.send_owner or "unknown"
        logger.info("Nudge (%s) skipped -- agent busy (%s)", reason, owner)
        return None

    reason_prefix = _build_reason_prefix(reason, **context)

    # Use ContextInjector for unified grounding + ambient context
    prompt = await agent.enrich("", turn_prefix=reason_prefix, include_ambient=True)

    logger.info("Nudge (%s): sending prompt (%d chars)", reason, len(prompt))

    try:
        response = await collect_response(agent, prompt, owner="nudge") or None
    except Exception as e:
        logger.warning("Nudge (%s) failed: %s", reason, e)
        return None

    if response:
        logger.info("Nudge response (%s): %s", reason, response[:200])
    return response


def _build_reason_prefix(reason: str, **context) -> str:
    """Build the reason-specific prefix for the nudge prompt."""
    parts: list[str] = [f"[{reason}]"]

    if reason == "timer":
        name = context.get("timer_name", "?")
        label = context.get("timer_label", "")
        parts.append(f"Timer '{name}' fired" + (f": {label}" if label else ""))
    elif reason == "reflect":
        parts.append("Reflect requested. Run /reflect to process pending sessions and consolidate memories.")

    return "\n".join(parts)
