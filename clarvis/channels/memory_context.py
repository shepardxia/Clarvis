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
    memory_service: Any,
    visibility: str,
    transcript_messages: list[dict[str, str]],
) -> str:
    """Build a memory context block for session-start grounding.

    Calls ``memory_service.recall()`` with transcript context and formats
    the result as a ``<memory_context>`` block suitable for injection as
    a synthetic first turn.

    Returns empty string if memory is not ready or has no results.
    """
    if memory_service is None or not memory_service.ready:
        return ""

    try:
        # Use last user message as query, or generic
        query = "Recall relevant memories for this conversation."
        for msg in reversed(transcript_messages):
            if msg.get("role") == "user":
                query = msg["content"]
                break

        result = await memory_service.recall(
            query,
            visibility=visibility,
            context_messages=transcript_messages,
        )
    except Exception:
        logger.debug("Memory grounding recall failed", exc_info=True)
        return ""

    if "error" in result:
        return ""

    # Format into a concise block
    parts: list[str] = []

    categories = result.get("categories", [])
    if categories:
        cat_lines = []
        for cat in categories:
            if isinstance(cat, dict):
                name = cat.get("name", "")
                summary = cat.get("summary", "")
                if name:
                    cat_lines.append(f"- {name}: {summary}" if summary else f"- {name}")
        if cat_lines:
            parts.append("Categories:\n" + "\n".join(cat_lines))

    items = result.get("items", [])
    if items:
        item_lines = []
        for item in items[:10]:  # Cap at 10 to keep grounding compact
            if isinstance(item, dict):
                text = item.get("summary") or item.get("text") or ""
                if text:
                    item_lines.append(f"- {text}")
        if item_lines:
            parts.append("Memories:\n" + "\n".join(item_lines))

    facts = result.get("graphiti_facts", [])
    if facts:
        fact_lines = []
        for fact in facts[:5]:  # Cap at 5
            if isinstance(fact, dict):
                text = fact.get("fact") or fact.get("text") or ""
                if text:
                    fact_lines.append(f"- {text}")
            elif isinstance(fact, str):
                fact_lines.append(f"- {fact}")
        if fact_lines:
            parts.append("Facts:\n" + "\n".join(fact_lines))

    if not parts:
        return ""

    body = "\n\n".join(parts)
    # Truncate if too long (keep grounding under ~2000 chars)
    if len(body) > 2000:
        body = body[:1997] + "..."

    return f"<memory_context>\n{body}\n</memory_context>"
