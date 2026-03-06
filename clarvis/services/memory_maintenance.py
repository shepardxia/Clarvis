"""Memory maintenance — legacy retain support.

Reflection, extraction, and consolidation are now handled by the nudge
system: WakeupManager nudges the persistent Clarvis agent, which runs
/reflect to extract atomic facts and consolidate.

This module is retained temporarily for the TranscriptReader watermark
machinery used by retain_sessions(). Once the nudge system is proven
stable, this can be removed entirely.
"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from clarvis.vendor.hindsight.engine.retain.types import FactInput

if TYPE_CHECKING:
    from clarvis.agent.memory.transcript_reader import TranscriptReader
    from clarvis.core.context import AppContext
    from clarvis.memory.store import HindsightStore
    from clarvis.services.context_accumulator import ContextAccumulator

logger = logging.getLogger(__name__)


class MemoryMaintenanceService:
    """Legacy retain — ingest transcripts as raw experience facts.

    Note: This path stores raw transcripts as single FactInput objects.
    It is superseded by the nudge → /reflect path where Clarvis extracts
    atomic facts. Kept temporarily for watermark compatibility.
    """

    def __init__(
        self,
        ctx: "AppContext",
        store: "HindsightStore",
        context_accumulator: "ContextAccumulator",
        transcript_reader: "TranscriptReader",
    ):
        self._ctx = ctx
        self._store = store
        self._accumulator = context_accumulator
        self._reader = transcript_reader

    async def retain_sessions(self) -> dict[str, Any]:
        """Ingest all pending session transcripts into memory.

        Returns:
            Summary dict with retained/skipped counts.
        """
        if not self._store or not self._store.ready:
            return {"error": "Memory store not available"}

        pending = self._accumulator.get_pending()
        sessions = pending.get("sessions_since_last", [])
        if not sessions:
            return {"retained": 0, "skipped": 0, "reason": "no pending sessions"}

        retained = 0
        skipped = 0

        for sess in sessions:
            transcript_path = sess.get("transcript_path")
            session_id = sess.get("session_id", "unknown")
            if not transcript_path or not Path(transcript_path).exists():
                skipped += 1
                continue

            result = await self._reader.ingest_session(session_id, transcript_path)

            if result.get("status") != "pending":
                skipped += 1
                continue

            content = result.get("new_content", "")
            if not content:
                skipped += 1
                continue

            project = sess.get("project", "unknown")
            fact = FactInput(
                fact_text=content,
                fact_type="experience",
                context=f"session:{session_id} project:{project}",
                tags=["session_transcript", project],
            )

            try:
                await self._store.store_facts([fact], bank="parletre")
                self._reader.mark_processed(session_id, result["byte_offset"])
                retained += 1
                logger.info("Retained session %s (%d bytes)", session_id[:8], len(content))
            except Exception:
                logger.warning("Failed to retain session %s", session_id[:8], exc_info=True)
                skipped += 1

        return {"retained": retained, "skipped": skipped}
