"""Multi-source JSONL session reader with per-source watermarks.

Reads Pi session files (pi-session.jsonl) incrementally using byte-offset
watermarks. Each source (e.g. clarvis, factoria) has an independent watermark.
"""

import json
import logging
import time
from pathlib import Path

from clarvis.core.persistence import json_load_safe, json_save_atomic

logger = logging.getLogger(__name__)

# Entry types that are metadata, not conversation content.
_SKIP_TYPES = {"session", "model_change", "thinking_level_change"}


def _parse_pi_messages(raw: str) -> list[dict[str, str]]:
    """Parse Pi JSONL and extract user/assistant text messages.

    Returns list of {"role": ..., "text": ...} dicts.
    """
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


def _filter_for_inbox(raw: str) -> list[str]:
    """Filter JSONL lines for inbox dump.

    Keeps all message entries (user, assistant, toolResult — including
    ambient context, tool calls, thinking blocks). Drops session metadata
    and system prompts.
    """
    kept = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") in _SKIP_TYPES:
            continue
        if entry.get("type") == "message":
            role = entry.get("message", {}).get("role")
            if role == "system":
                continue
        kept.append(line)
    return kept


class SessionReader:
    """Reads multiple Pi session JSONL files with per-source byte watermarks."""

    def __init__(self, sources: dict[str, Path], watermark_file: Path) -> None:
        self._sources = {k: Path(v) for k, v in sources.items()}
        self._watermark_file = Path(watermark_file)
        self._watermarks: dict[str, int] = json_load_safe(self._watermark_file) or {}
        self._pending_offsets: dict[str, int] = {}

    def _read_since_watermark(self, source: str) -> tuple[str, int] | None:
        """Read raw bytes from *source* since its watermark.

        Returns (raw_text, file_size) or None if nothing new.
        """
        path = self._sources.get(source)
        if not path or not path.exists():
            return None
        watermark = self._watermarks.get(source, 0)
        file_size = path.stat().st_size
        if watermark >= file_size:
            return None
        with open(path, "rb") as f:
            f.seek(watermark)
            raw = f.read().decode("utf-8", errors="replace")
        return raw, file_size

    def read_pending(self) -> dict[str, list[dict[str, str]]]:
        """Read new messages from all sources since their watermarks.

        Returns {source_name: [{"role": ..., "text": ...}, ...]}.
        """
        result: dict[str, list[dict[str, str]]] = {}
        for name in self._sources:
            chunk = self._read_since_watermark(name)
            if chunk is None:
                result[name] = []
                continue
            raw, file_size = chunk
            result[name] = _parse_pi_messages(raw)
            self._pending_offsets[name] = file_size
        return result

    def advance(self, source: str) -> None:
        """Advance watermark for a source after successful processing."""
        if source in self._pending_offsets:
            self._watermarks[source] = self._pending_offsets.pop(source)
            json_save_atomic(self._watermark_file, self._watermarks)

    def advance_all(self) -> None:
        """Advance watermarks for all sources."""
        if not self._pending_offsets:
            return
        for source in list(self._pending_offsets):
            self._watermarks[source] = self._pending_offsets.pop(source)
        json_save_atomic(self._watermark_file, self._watermarks)

    def flush_to_inbox(self, source: str, inbox_dir: Path) -> Path | None:
        """Dump unreflected content for *source* into inbox and advance watermark.

        Filters out session metadata and system prompts. Returns the
        path of the written file, or None if there was nothing to flush.
        """
        chunk = self._read_since_watermark(source)
        if chunk is None:
            return None
        raw, file_size = chunk

        lines = _filter_for_inbox(raw)
        if not lines:
            # Only metadata — advance watermark, nothing to dump.
            self._watermarks[source] = file_size
            json_save_atomic(self._watermark_file, self._watermarks)
            return None

        inbox_dir.mkdir(parents=True, exist_ok=True)
        out = inbox_dir / f"{source}_{int(time.time())}.jsonl"
        out.write_text("\n".join(lines) + "\n")

        self._watermarks[source] = file_size
        json_save_atomic(self._watermark_file, self._watermarks)
        logger.info("Flushed %d lines from %s to %s", len(lines), source, out.name)
        return out
