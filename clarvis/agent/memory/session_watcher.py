"""Session transcript watcher with byte-offset watermarks.

Replaces IngestionPipeline.  Tracks per-session byte offsets into JSONL
transcript files and exposes unprocessed content for the retain skill to
consume.  The actual memory extraction is agent-driven (the retain skill
reads the content and calls ``memory_add``), not pipeline-driven.

Typical flow::

    watcher = SessionWatcher(sessions_dir, watermark_path)
    pending = await watcher.scan()
    # Agent processes pending[0]["new_content"], then:
    watcher.mark_processed(pending[0]["session_id"], pending[0]["byte_offset"])
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clarvis.core.persistence import json_load_safe, json_save_atomic

logger = logging.getLogger(__name__)

_ELIGIBLE_ROLES = frozenset({"user", "assistant", "human"})


class SessionWatcher:
    """Watches Claude Code session transcripts for new content.

    Tracks byte-offset watermarks per session file.  Exposes unprocessed
    transcript content for the retain skill to process.  Does NOT call any
    memory backend directly -- the agent decides what to retain.

    State is persisted as ``{watermark_path}`` using atomic JSON writes.
    """

    def __init__(
        self,
        sessions_dir: Path,
        watermark_path: Path,
    ) -> None:
        self._sessions_dir = Path(sessions_dir).expanduser()
        self._watermark_path = Path(watermark_path).expanduser()
        self._state: dict[str, Any] = self._load_state()

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> dict[str, Any]:
        data = json_load_safe(self._watermark_path)
        if data is None:
            return {"watermarks": {}, "last_scan_ts": None}
        data.setdefault("watermarks", {})
        data.setdefault("last_scan_ts", None)
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
        """Update watermark for a session after the retain skill processes it."""
        self._state["watermarks"][session_id] = byte_offset
        self._state["last_scan_ts"] = datetime.now(timezone.utc).isoformat()
        self._save_state()

    # ------------------------------------------------------------------
    # Staleness
    # ------------------------------------------------------------------

    @property
    def last_scan_ts(self) -> str | None:
        """ISO timestamp of the last successful scan/process, or ``None``."""
        return self._state.get("last_scan_ts")

    def is_stale(self, staleness_hours: int = 24) -> bool:
        """Return ``True`` if no processing has occurred within *staleness_hours*."""
        ts = self.last_scan_ts
        if ts is None:
            return True
        try:
            last = datetime.fromisoformat(ts)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            return (now - last).total_seconds() > staleness_hours * 3600
        except (ValueError, TypeError):
            return True

    # ------------------------------------------------------------------
    # Scanning
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

    def _find_transcript_files(self) -> list[tuple[str, Path]]:
        """Discover JSONL transcript files in the sessions directory.

        Returns a list of ``(session_id, path)`` tuples.  The session_id
        is derived from the file stem or parent directory name.
        """
        if not self._sessions_dir.is_dir():
            return []

        results: list[tuple[str, Path]] = []

        # Pattern 1: direct .jsonl files under sessions_dir
        for p in self._sessions_dir.glob("*.jsonl"):
            results.append((p.stem, p))

        # Pattern 2: subdirectories containing a transcript file
        for d in self._sessions_dir.iterdir():
            if not d.is_dir():
                continue
            for name in ("transcript.jsonl", "conversation.jsonl"):
                candidate = d / name
                if candidate.is_file():
                    results.append((d.name, candidate))
                    break

        return results

    async def scan(self) -> list[dict[str, Any]]:
        """Scan for new sessions and content.

        Returns a list of pending session dicts, each containing:

        - ``session_id``: unique session identifier
        - ``path``: Path to the transcript file
        - ``new_content``: formatted text of new messages (after watermark)
        - ``messages``: list of parsed ``{"role", "content"}`` dicts
        - ``message_count``: number of new messages
        - ``byte_offset``: byte offset to pass to ``mark_processed()``
        - ``last_timestamp``: ISO timestamp of the latest message (if available)
        """
        transcripts = self._find_transcript_files()
        pending: list[dict[str, Any]] = []

        for session_id, path in transcripts:
            watermark = self.get_watermark(session_id)
            try:
                raw_data, messages, new_offset = self._read_new_content(path, watermark)
            except OSError:
                logger.debug("Failed to read %s", path, exc_info=True)
                continue

            if not messages:
                continue

            # Format as readable text for the retain skill
            content_lines = [f"{m['role']}: {m['content']}" for m in messages]
            new_content = "\n".join(content_lines)

            # Try to extract a timestamp from the last entry
            last_ts = None
            try:
                # Re-read the last raw JSONL line for timestamp
                for raw_line in reversed(raw_data.splitlines()):
                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue
                    entry = json.loads(raw_line)
                    ts = entry.get("timestamp") or entry.get("ts") or entry.get("created_at")
                    if ts:
                        last_ts = ts
                    break
            except (json.JSONDecodeError, KeyError):
                pass

            pending.append(
                {
                    "session_id": session_id,
                    "path": path,
                    "new_content": new_content,
                    "messages": messages,
                    "message_count": len(messages),
                    "byte_offset": new_offset,
                    "last_timestamp": last_ts,
                }
            )

        return pending

    async def get_pending_sessions(self) -> list[dict[str, Any]]:
        """Return sessions with unprocessed content.

        Convenience alias for ``scan()``.
        """
        return await self.scan()

    # ------------------------------------------------------------------
    # Legacy compatibility
    # ------------------------------------------------------------------

    async def ingest_session(
        self,
        session_key: str,
        transcript_path: Path,
        *,
        dataset: str = "parletre",
    ) -> dict[str, Any]:
        """Legacy compat: scan a single known transcript.

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
            # Advance watermark even when empty (same as IngestionPipeline)
            self.mark_processed(session_key, new_offset)
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
