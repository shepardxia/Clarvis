"""Multi-source JSONL session reader with per-source watermarks.

Reads Pi session files (pi-session.jsonl) incrementally using byte-offset
watermarks. Each source (e.g. clarvis, factoria) has an independent watermark.
"""

import json
import logging
from pathlib import Path

from clarvis.core.persistence import json_load_safe, json_save_atomic

logger = logging.getLogger(__name__)


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


class SessionReader:
    """Reads multiple Pi session JSONL files with per-source byte watermarks."""

    def __init__(self, sources: dict[str, Path], watermark_file: Path) -> None:
        self._sources = {k: Path(v) for k, v in sources.items()}
        self._watermark_file = Path(watermark_file)
        self._watermarks: dict[str, int] = json_load_safe(self._watermark_file) or {}
        self._pending_offsets: dict[str, int] = {}

    def read_pending(self) -> dict[str, list[dict[str, str]]]:
        """Read new messages from all sources since their watermarks.

        Returns {source_name: [{"role": ..., "text": ...}, ...]}.
        """
        result: dict[str, list[dict[str, str]]] = {}
        for name, path in self._sources.items():
            if not path.exists():
                result[name] = []
                continue
            watermark = self._watermarks.get(name, 0)
            file_size = path.stat().st_size
            if watermark >= file_size:
                result[name] = []
                continue
            with open(path, "rb") as f:
                f.seek(watermark)
                raw = f.read().decode("utf-8", errors="replace")
            messages = _parse_pi_messages(raw)
            self._pending_offsets[name] = file_size
            result[name] = messages
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
