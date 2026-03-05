"""Automated memory maintenance: retain sessions + reflect consolidation.

Retain reads pending session transcripts (captured by ContextAccumulator from
Stop hooks) and stores them as experience facts via HindsightStore.store_facts().
Reflect retains pending sessions first, then spawns an ephemeral agent with the
reflect skill to consolidate facts into observations and refresh mental models.

Registered as a single scheduler task; the daemon wires it in ``run()``.
"""

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from clarvis.vendor.hindsight.engine.retain.types import FactInput

if TYPE_CHECKING:
    from clarvis.agent.agent import Agent
    from clarvis.agent.memory.transcript_reader import TranscriptReader
    from clarvis.core.context import AppContext
    from clarvis.memory.store import HindsightStore
    from clarvis.services.context_accumulator import ContextAccumulator

logger = logging.getLogger(__name__)


class MemoryMaintenanceService:
    """Orchestrates automated retain + reflect cycles."""

    def __init__(
        self,
        ctx: "AppContext",
        store: "HindsightStore",
        context_accumulator: "ContextAccumulator",
        transcript_reader: "TranscriptReader",
        agent_factory: Callable[[], "Agent"],
    ):
        self._ctx = ctx
        self._store = store
        self._accumulator = context_accumulator
        self._reader = transcript_reader
        self._agent_factory = agent_factory
        self._last_reflect_ts: float = 0.0

    # ------------------------------------------------------------------
    # Retain: ingest pending session transcripts as experience facts
    # ------------------------------------------------------------------

    async def retain_sessions(self) -> dict[str, Any]:
        """Ingest all pending session transcripts into memory.

        Called internally by reflect() — not scheduled independently.
        Always retains everything pending; no recency filtering.

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

            # Read new content via session watcher
            result = await self._reader.ingest_session(session_id, transcript_path)

            if result.get("status") != "pending":
                skipped += 1
                continue

            content = result.get("new_content", "")
            if not content:
                skipped += 1
                continue

            # Store as experience fact
            project = sess.get("project", "unknown")
            fact = FactInput(
                fact_text=content,
                fact_type="experience",
                context=f"session:{session_id} project:{project}",
                tags=["session_transcript", project],
            )

            try:
                await self._store.store_facts([fact], bank="parletre")
                # Advance watermark only after successful storage
                self._reader.mark_processed(session_id, result["byte_offset"])
                retained += 1
                logger.info("Retained session %s (%d bytes)", session_id[:8], len(content))
            except Exception:
                logger.warning("Failed to retain session %s", session_id[:8], exc_info=True)
                skipped += 1

        return {"retained": retained, "skipped": skipped}

    # ------------------------------------------------------------------
    # Reflect: retain first, then consolidate via agent
    # ------------------------------------------------------------------

    async def reflect(self, force: bool = False) -> dict[str, Any]:
        """Retain pending sessions, then run consolidation.

        Always retains first (no-op if nothing pending). Then checks whether
        consolidation is warranted based on fact threshold and staleness.

        Args:
            force: If True, force retain of all sessions and always reflect
                   regardless of thresholds. Used by ``clarvis rem``.
        """
        if not self._store or not self._store.ready:
            return {"error": "Memory store not available"}

        # Always retain first — no-op if nothing pending
        try:
            retain_result = await self.retain_sessions()
        except Exception:
            logger.debug("Retain before reflect failed", exc_info=True)
            retain_result = {"error": "retain failed"}

        # Check if there's enough work to justify reflecting
        try:
            result = await self._store.get_unconsolidated("parletre")
            facts = result.get("facts", []) if isinstance(result, dict) else []
            pending_count = len(facts)
        except Exception:
            logger.debug("Failed to check unconsolidated facts", exc_info=True)
            pending_count = 0

        mem_cfg = self._ctx.config.memory
        threshold = mem_cfg.reflect_fact_threshold
        fallback_hours = mem_cfg.reflect_staleness_hours
        hours_since_reflect = (time.time() - self._last_reflect_ts) / 3600

        should_reflect = force or (
            pending_count >= threshold or (hours_since_reflect >= fallback_hours and pending_count > 0)
        )

        if not should_reflect:
            return {
                "status": "skipped",
                "retain": retain_result,
                "reason": f"{pending_count} facts pending (threshold: {threshold}), "
                f"{hours_since_reflect:.1f}h since last reflect (fallback: {fallback_hours}h)",
            }

        logger.info(
            "Starting reflect: %d unconsolidated facts, %.1fh since last reflect",
            pending_count,
            hours_since_reflect,
        )

        try:
            agent = self._agent_factory()
            await agent.connect()
            response_text = ""
            async for chunk in agent.send("/reflect"):
                if chunk:
                    response_text += chunk
            await agent.disconnect()
        except Exception:
            logger.warning("Reflect agent failed", exc_info=True)
            return {"status": "error", "retain": retain_result, "reason": "agent failed"}

        self._last_reflect_ts = time.time()
        logger.info("Reflect complete: %d chars response", len(response_text))
        return {
            "status": "ok",
            "retain": retain_result,
            "facts_pending": pending_count,
            "response_length": len(response_text),
        }

    # ------------------------------------------------------------------
    # Force: manual trigger (clarvis rem)
    # ------------------------------------------------------------------

    async def on_force_rem(self) -> dict[str, Any]:
        """Force retain + reflect. Called by ``clarvis rem``."""
        return await self.reflect(force=True)

    # ------------------------------------------------------------------
    # Scheduled tick: periodic maintenance check
    # ------------------------------------------------------------------

    async def maintenance_tick(self) -> None:
        """Periodic maintenance — reflect if needed (retains internally).

        Registered with the Scheduler.
        """
        try:
            result = await self.reflect()
            if result.get("status") == "ok":
                logger.info("Maintenance reflect: %s", result)
        except Exception:
            logger.debug("Maintenance reflect failed", exc_info=True)
