"""Memory grounding utilities for channel session startup.

Provides functions to read recent transcript and build a memory context
block that's injected as a synthetic first turn when a new session starts.
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def read_recent_transcript(
    path: Path | str,
    max_lines: int = 20,
) -> list[dict[str, str]]:
    """Read last *max_lines* entries from a JSONL transcript file.

    Returns list of ``{"role": "user"|"assistant", "content": "..."}``.
    Silently returns empty list on missing file or parse errors.
    """
    path = Path(path)
    if not path.is_file():
        return []
    messages: list[dict[str, str]] = []
    try:
        lines = path.read_text().strip().splitlines()
        for line in lines[-max_lines:]:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            sender = entry.get("sender", "")
            content = entry.get("content", "")
            if not content:
                continue
            role = "assistant" if sender == "clarvis" else "user"
            messages.append({"role": role, "content": content[:2000]})
    except Exception:
        logger.debug("Failed to read transcript at %s", path, exc_info=True)
    return messages


async def build_memory_grounding(
    hindsight_backend: Any,
    bank: str,
    transcript_messages: list[dict[str, str]],
) -> str:
    """Build a memory context block for session-start grounding.

    Calls ``hindsight_backend.recall()`` with transcript context and formats
    the result as a ``<memory_context>`` block suitable for injection as
    a synthetic first turn.

    Returns empty string if memory is not ready or has no results.

    Args:
        hindsight_backend: HindsightBackend instance (or any object with
            ``.ready`` property and async ``.recall()`` method).
        bank: Hindsight bank to recall from (e.g. 'parletre', 'agora').
        transcript_messages: Recent transcript messages for context.
    """
    if hindsight_backend is None or not hindsight_backend.ready:
        return ""

    try:
        # Use last user message as query, or generic
        query = "Recall relevant memories for this conversation."
        for msg in reversed(transcript_messages):
            if msg.get("role") == "user":
                query = msg["content"]
                break

        result = await hindsight_backend.recall(
            query,
            bank=bank,
            max_tokens=4096,
        )
    except Exception:
        logger.debug("Memory grounding recall failed", exc_info=True)
        return ""

    if "error" in result:
        return ""

    # Format Hindsight recall result into a concise block
    parts: list[str] = []

    # Results / facts from recall
    results = result.get("results") or result.get("facts") or []
    if results:
        fact_lines = []
        for fact in results[:15]:  # Cap at 15 to keep grounding compact
            if isinstance(fact, dict):
                ftype = fact.get("fact_type") or fact.get("type") or ""
                text = fact.get("content") or fact.get("text") or ""
                confidence = fact.get("confidence")
                if text:
                    prefix = f"[{ftype}] " if ftype else ""
                    suffix = f" (conf: {confidence})" if confidence is not None else ""
                    fact_lines.append(f"- {prefix}{text}{suffix}")
            elif isinstance(fact, str):
                fact_lines.append(f"- {fact}")
        if fact_lines:
            parts.append("Memories:\n" + "\n".join(fact_lines))

    # Entities
    entities = result.get("entities", [])
    if entities:
        entity_lines = []
        for ent in entities[:10]:
            if isinstance(ent, dict):
                name = ent.get("name", "")
                if name:
                    entity_lines.append(f"- {name}")
            elif isinstance(ent, str):
                entity_lines.append(f"- {ent}")
        if entity_lines:
            parts.append("Entities:\n" + "\n".join(entity_lines))

    if not parts:
        return ""

    body = "\n\n".join(parts)
    # Truncate if too long (keep grounding under ~2000 chars)
    if len(body) > 2000:
        body = body[:1997] + "..."

    return f"<memory_context>\n{body}\n</memory_context>"
