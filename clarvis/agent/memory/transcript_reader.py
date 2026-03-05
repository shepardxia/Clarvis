"""Transcript reader with byte-offset watermarks.

Reads JSONL session transcripts on demand and tracks per-session byte
offsets so only new content is returned on subsequent reads.  Called by
the retain pipeline — does NOT scan or discover sessions on its own.

Typical flow::

    reader = TranscriptReader(watermark_path)
    result = await reader.ingest_session(session_id, transcript_path)
    # Caller processes result["new_content"], then:
    reader.mark_processed(session_id, result["byte_offset"])
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clarvis.core.persistence import json_load_safe, json_save_atomic

logger = logging.getLogger(__name__)

_ELIGIBLE_ROLES = frozenset({"user", "assistant", "human"})


class TranscriptReader:
    """Reads session transcripts and tracks watermarks.

    Parses JSONL transcript files, filters to eligible roles, and returns
    new content past the watermark.  Does NOT call any memory backend
    directly — the caller decides what to retain.

    State is persisted as ``{watermark_path}`` using atomic JSON writes.
    """

    def __init__(self, watermark_path: Path) -> None:
        self._watermark_path = Path(watermark_path).expanduser()
        self._state: dict[str, Any] = self._load_state()

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> dict[str, Any]:
        data = json_load_safe(self._watermark_path)
        if data is None:
            return {"watermarks": {}}
        data.setdefault("watermarks", {})
        return data

    def _save_state(self) -> None:
        json_save_atomic(self._watermark_path, self._state)

    # ------------------------------------------------------------------
    # Watermark helpers
    # ------------------------------------------------------------------

    def get_watermark(self, session_id: str) -> int:
        """Return the byte offset for *session_id* (default ``0``)."""
        return self._state["watermarks"].get(session_id, 0)

    def mark_processed(self, session_id: str, byte_offset: int) -> None:
        """Update watermark for a session after content is retained."""
        self._state["watermarks"][session_id] = byte_offset
        self._state["last_processed_ts"] = datetime.now(timezone.utc).isoformat()
        self._save_state()

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_transcript(raw_data: str) -> list[dict[str, str]]:
        """Parse JSONL text and extract eligible role/content pairs.

        Returns a list of ``{"role": ..., "content": ...}`` dicts for
        lines whose role/type is in ``_ELIGIBLE_ROLES``.
        """
        messages: list[dict[str, str]] = []
        for raw_line in raw_data.splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                entry = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            content = entry.get("content")
            if content is None:
                continue
            role = entry.get("role") or entry.get("type")
            if role in _ELIGIBLE_ROLES:
                messages.append({"role": role, "content": content})
        return messages

    def _read_new_content(self, path: Path, watermark: int) -> tuple[str, list[dict[str, str]], int]:
        """Read content from *path* after *watermark*.

        Returns ``(raw_text, parsed_messages, new_byte_offset)``.
        """
        file_size = path.stat().st_size
        if watermark >= file_size:
            return "", [], file_size

        with open(path, "r", encoding="utf-8") as f:
            f.seek(watermark)
            raw_data = f.read()

        messages = self._parse_transcript(raw_data)
        return raw_data, messages, file_size

    async def ingest_session(
        self,
        session_key: str,
        transcript_path: Path,
    ) -> dict[str, Any]:
        """Read new content from a known transcript.

        Does NOT call any memory backend.  Returns the pending content
        dict if there is new content, or a "skipped" status dict.

        The caller is responsible for processing the content and calling
        ``mark_processed()`` afterwards.
        """
        path = Path(transcript_path)
        if not path.exists():
            return {"status": "skipped", "reason": "transcript not found"}

        watermark = self.get_watermark(session_key)
        try:
            raw_data, messages, new_offset = self._read_new_content(path, watermark)
        except OSError:
            return {"status": "skipped", "reason": "read error"}

        if not messages:
            return {"status": "skipped", "reason": "no eligible content"}

        content_lines = [f"{m['role']}: {m['content']}" for m in messages]

        return {
            "status": "pending",
            "session_id": session_key,
            "new_content": "\n".join(content_lines),
            "messages": messages,
            "message_count": len(messages),
            "byte_offset": new_offset,
        }
