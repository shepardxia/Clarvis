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
    from ..agent.agent import auto_approve_extension_ui

    # Skip if agent is busy with voice (voice has priority)
    if agent.is_busy:
        owner = agent.send_owner or "unknown"
        logger.info("Nudge (%s) skipped -- agent busy (%s)", reason, owner)
        return None

    reason_prefix = _build_reason_prefix(reason, **context)

    # Use ContextInjector for unified grounding + ambient context
    if agent.context:
        prompt = await agent.context.enrich("", turn_prefix=reason_prefix)
    else:
        prompt = reason_prefix

    logger.info("Nudge (%s): sending prompt (%d chars)", reason, len(prompt))

    chunks: list[str] = []
    try:
        async for event in agent.send(prompt, owner="nudge"):
            etype = event.get("type")
            if etype == "extension_ui_request":
                auto_approve_extension_ui(agent, event)
            elif etype == "message_update":
                delta = event.get("assistantMessageEvent", {})
                if delta.get("type") == "text_delta":
                    chunks.append(delta.get("delta", ""))
            elif etype == "agent_end":
                break
    except Exception as e:
        logger.warning("Nudge (%s) failed: %s", reason, e)
        return None

    response = "".join(chunks).strip() if chunks else None
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
