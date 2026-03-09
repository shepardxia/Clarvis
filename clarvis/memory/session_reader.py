"""Parse Pi session JSONL files into structured messages."""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def parse_session(path: Path) -> list[dict[str, str]]:
    """Parse a Pi session JSONL file, return [{"role": ..., "text": ...}].

    Extracts user and assistant text messages, skipping metadata entries
    (session, model_change, system prompts, etc.).
    """
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return []
    messages = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "message":
            continue
        msg = entry.get("message", {})
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        # Extract text from content blocks
        content = msg.get("content", [])
        text_parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif isinstance(block, str):
                text_parts.append(block)
        if text_parts:
            messages.append({"role": role, "text": "\n".join(text_parts)})
    return messages
