"""Thin wrapper around Hindsight MemoryEngine.

Manages lifecycle, maps dataset names to bank_ids,
exposes retain/recall/reflect/update/forget/list/consolidate.
"""

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class HindsightBackend:
    """Conversational memory backend powered by Hindsight MemoryEngine.

    Wraps the MemoryEngine with:
    - Lifecycle management (start/stop/ready)
    - Bank-id mapping (parletre, agora)
    - Simplified async API for Clarvis services and MCP tools
    """

    def __init__(
        self,
        *,
        db_url: str = "pg0",
        llm_provider: str = "anthropic",
        api_key: str | None = None,
        model: str | None = None,
        banks: dict[str, dict] | None = None,
    ) -> None:
        self._db_url = db_url
        self._llm_provider = llm_provider
        self._api_key = api_key
        self._model = model
        self._banks = banks or {
            "parletre": {"visibility": "master"},
            "agora": {"visibility": "all"},
        }
        self._engine: Any = None
        self._ready = False

    # ── Lifecycle ───────────────────────────────────────────────────

    async def start(self) -> None:
        """Initialize MemoryEngine — starts pg0, runs migrations, creates pool."""
        from clarvis.vendor.hindsight.engine.memory_engine import MemoryEngine

        self._engine = MemoryEngine(
            db_url=self._db_url,
            memory_llm_provider=self._llm_provider,
            memory_llm_api_key=self._api_key,
            memory_llm_model=self._model,
        )
        await self._engine.initialize()
        self._ready = True
        logger.info(
            "HindsightBackend started (banks: %s)",
            ", ".join(self._banks),
        )

    async def stop(self) -> None:
        """Shut down the MemoryEngine and release resources."""
        if self._engine is not None:
            await self._engine.close()
            self._engine = None
        self._ready = False
        logger.info("HindsightBackend stopped")

    @property
    def ready(self) -> bool:
        return self._ready

    # ── Helpers ─────────────────────────────────────────────────────

    def _request_context(self):
        """Build an internal RequestContext (skips tenant auth)."""
        from clarvis.vendor.hindsight.models import RequestContext

        return RequestContext(internal=True)

    def _validate_bank(self, bank: str) -> None:
        if bank not in self._banks:
            raise ValueError(f"Unknown bank '{bank}'. Available: {', '.join(self._banks)}")

    def visible_banks(self, visibility: str = "master") -> list[str]:
        """Return bank names visible at the given access level."""
        if visibility == "master":
            return list(self._banks)
        return [
            name
            for name, cfg in self._banks.items()
            if cfg.get("visibility") == visibility or cfg.get("visibility") == "all"
        ]

    # ── Core operations ─────────────────────────────────────────────

    async def retain(
        self,
        content: str,
        *,
        bank: str = "parletre",
        fact_type: str | None = None,
        confidence: float | None = None,
        event_date: datetime | None = None,
        context: str = "",
    ) -> list[dict]:
        """Retain a memory. Returns list of created fact dicts with IDs and types.

        Uses retain_async (single-item convenience wrapper). For batch
        ingestion, call retain_batch() directly.
        """
        self._validate_bank(bank)
        unit_ids = await self._engine.retain_async(
            bank_id=bank,
            content=content,
            context=context,
            event_date=event_date,
            fact_type_override=fact_type,
            confidence_score=confidence,
            request_context=self._request_context(),
        )
        # Return structured results — unit_ids is a list of UUID strings
        return [{"id": uid, "fact_type": fact_type or "world"} for uid in unit_ids]

    async def retain_batch(
        self,
        contents: list[dict],
        *,
        bank: str = "parletre",
        fact_type: str | None = None,
        confidence: float | None = None,
    ) -> list[list[dict]]:
        """Batch-retain multiple content items.

        Each item in *contents* is a dict with keys:
        - "content" (required): text to store
        - "context" (optional): context string
        - "event_date" (optional): datetime
        """
        self._validate_bank(bank)
        result = await self._engine.retain_batch_async(
            bank_id=bank,
            contents=contents,
            request_context=self._request_context(),
            fact_type_override=fact_type,
            confidence_score=confidence,
        )
        # result is list[list[str]] — one list of unit IDs per content item
        return [[{"id": uid, "fact_type": fact_type or "world"} for uid in group] for group in result]

    async def recall(
        self,
        query: str,
        *,
        bank: str = "parletre",
        max_tokens: int = 4096,
        fact_type: list[str] | None = None,
    ) -> dict:
        """Recall memories with token budget. Used for context building + search.

        Returns a dict with 'results' (list of MemoryFact dicts),
        'entities', and 'chunks'.
        """
        self._validate_bank(bank)
        recall_result = await self._engine.recall_async(
            bank_id=bank,
            query=query,
            max_tokens=max_tokens,
            fact_type=fact_type,
            request_context=self._request_context(),
        )
        # Convert Pydantic model to dict for serialization
        return recall_result.model_dump()

    async def reflect(
        self,
        query: str,
        *,
        bank: str = "parletre",
        context: str | None = None,
        max_tokens: int = 4096,
    ) -> dict:
        """Agentic reflection — iterative tool-augmented reasoning over memories.

        Returns a dict with 'text', 'based_on', 'usage', etc.
        """
        self._validate_bank(bank)
        result = await self._engine.reflect_async(
            bank_id=bank,
            query=query,
            context=context,
            max_tokens=max_tokens,
            request_context=self._request_context(),
        )
        return result.model_dump()

    async def update(
        self,
        fact_id: str,
        *,
        bank: str = "parletre",
        content: str | None = None,
        confidence: float | None = None,
        fact_type: str | None = None,
    ) -> dict:
        """Update an existing memory unit.

        Currently re-retains with the new content (Hindsight does not expose
        an atomic update-in-place). Deletes the old unit first if content
        changed.
        """
        self._validate_bank(bank)
        rc = self._request_context()

        if content is not None:
            # Delete old, retain new
            await self._engine.delete_memory_unit(fact_id, request_context=rc)
            new_ids = await self._engine.retain_async(
                bank_id=bank,
                content=content,
                fact_type_override=fact_type,
                confidence_score=confidence,
                request_context=rc,
            )
            return {
                "success": True,
                "old_id": fact_id,
                "new_ids": new_ids,
                "message": "Memory replaced",
            }

        # Metadata-only update not supported by MemoryEngine — return info
        return {
            "success": False,
            "message": "Content is required for update (metadata-only updates not supported)",
        }

    async def forget(self, fact_id: str) -> dict:
        """Delete a memory unit by ID."""
        result = await self._engine.delete_memory_unit(
            fact_id,
            request_context=self._request_context(),
        )
        return result

    async def list_memories(
        self,
        *,
        bank: str = "parletre",
        fact_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
        search_query: str | None = None,
    ) -> dict:
        """List memory units with optional filtering.

        Returns dict with 'items', 'total', 'limit', 'offset'.
        """
        self._validate_bank(bank)
        return await self._engine.list_memory_units(
            bank_id=bank,
            fact_type=fact_type,
            search_query=search_query,
            limit=limit,
            offset=offset,
            request_context=self._request_context(),
        )

    async def get_memory(self, fact_id: str, *, bank: str = "parletre") -> dict | None:
        """Get a single memory unit by ID."""
        self._validate_bank(bank)
        return await self._engine.get_memory_unit(
            bank_id=bank,
            memory_id=fact_id,
            request_context=self._request_context(),
        )

    async def consolidate(self, *, bank: str = "parletre") -> dict:
        """Run background consolidation (observation synthesis).

        Returns dict with 'processed', 'created', 'updated', 'skipped'.
        """
        self._validate_bank(bank)
        return await self._engine.run_consolidation(
            bank_id=bank,
            request_context=self._request_context(),
        )

    async def list_banks(self) -> list[dict]:
        """List all configured banks with their profiles."""
        result = await self._engine.list_banks(
            request_context=self._request_context(),
        )
        return result
