"""Incremental transcript ingestion with byte-offset watermarks."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from clarvis.core.persistence import json_load_safe, json_save_atomic

logger = logging.getLogger(__name__)


class _MemoryService(Protocol):
    """Minimal protocol for the memory backend used by IngestionPipeline."""

    async def ingest_transcript(self, text: str, *, dataset: str) -> dict: ...


class IngestionPipeline:
    """Incremental JSONL transcript ingestion with per-session watermarks.

    State is persisted as ``{state_dir}/ingestion_state.json`` using atomic
    JSON writes.  Each session key tracks a byte offset so that only new
    content is fed to the memory service on subsequent runs.
    """

    _ELIGIBLE_ROLES = {"user", "assistant", "human"}

    def __init__(self, state_dir: Path, memory_service: Any) -> None:
        self._state_dir = Path(state_dir)
        self._memory = memory_service
        self._state_path = self._state_dir / "ingestion_state.json"
        self._state: dict[str, Any] = self._load_state()

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> dict[str, Any]:
        data = json_load_safe(self._state_path)
        if data is None:
            return {"watermarks": {}, "last_write_ts": None}
        # Ensure required keys exist.
        data.setdefault("watermarks", {})
        data.setdefault("last_write_ts", None)
        return data

    def _save_state(self) -> None:
        json_save_atomic(self._state_path, self._state)

    # ------------------------------------------------------------------
    # Watermark helpers
    # ------------------------------------------------------------------

    def get_watermark(self, session_key: str) -> int:
        """Return the byte offset for *session_key* (default ``0``)."""
        return self._state["watermarks"].get(session_key, 0)

    def set_watermark(self, session_key: str, offset: int) -> None:
        """Set the byte offset for *session_key* and persist."""
        self._state["watermarks"][session_key] = offset
        self._save_state()

    # ------------------------------------------------------------------
    # Staleness
    # ------------------------------------------------------------------

    @property
    def last_write_ts(self) -> str | None:
        """ISO timestamp of the last successful ingest, or ``None``."""
        return self._state.get("last_write_ts")

    def is_stale(self, staleness_hours: int = 24) -> bool:
        """Return ``True`` if no ingest has occurred within *staleness_hours*."""
        ts = self.last_write_ts
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
    # Ingestion
    # ------------------------------------------------------------------

    async def ingest_session(
        self,
        session_key: str,
        transcript_path: Path,
        *,
        dataset: str,
    ) -> dict:
        """Ingest new JSONL content from *transcript_path* since the last watermark.

        Returns a status dict: ``{"status": "ok", ...}`` on success,
        ``{"status": "skipped", "reason": ...}`` when there is nothing new.
        """
        transcript_path = Path(transcript_path)
        if not transcript_path.exists():
            return {"status": "skipped", "reason": "transcript not found"}

        file_size = transcript_path.stat().st_size
        watermark = self.get_watermark(session_key)

        if watermark >= file_size:
            return {"status": "skipped", "reason": "no new content"}

        # Read only the new bytes.
        with open(transcript_path, "r", encoding="utf-8") as f:
            f.seek(watermark)
            new_data = f.read()

        # Parse JSONL lines and extract eligible role/content pairs.
        lines: list[str] = []
        for raw_line in new_data.splitlines():
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
            if role in self._ELIGIBLE_ROLES:
                lines.append(f"{role}: {content}")

        if not lines:
            # Advance watermark even if nothing extractable.
            self.set_watermark(session_key, file_size)
            return {"status": "skipped", "reason": "no eligible content"}

        transcript_text = "\n".join(lines)
        result = await self._memory.ingest_transcript(transcript_text, dataset=dataset)

        # Advance watermark and record timestamp.
        self._state["watermarks"][session_key] = file_size
        self._state["last_write_ts"] = datetime.now(timezone.utc).isoformat()
        self._save_state()

        return {"status": "ok", "lines": len(lines), "result": result}
