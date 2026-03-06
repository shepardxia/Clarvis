"""HindsightStore — Level 2 interface to Hindsight's MemoryEngine.

Wraps MemoryEngine with clean async API that hides Hindsight internals
(RequestContext, pool management, tenant auth). All methods validate bank
names against configured banks and create internal request contexts.

Clarvis is the agent; this is the storage and retrieval layer.
"""

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class HindsightStore:
    """Level 2 memory storage interface.

    Exposes the full non-LLM surface area of Hindsight:
    facts, observations, mental models, directives, entities, tags,
    bank config, documents, and retrieval (TEMPR + semantic search).
    """

    def __init__(
        self,
        *,
        db_url: str = "pg0",
        banks: dict[str, dict] | None = None,
    ) -> None:
        self._db_url = db_url
        self._banks = banks or {
            "parletre": {"visibility": "master"},
            "agora": {"visibility": "all"},
        }
        self._engine: Any = None
        self._ready = False

    # ── Lifecycle ──────────────────────────────────────────────────

    async def start(self) -> None:
        """Initialize MemoryEngine — starts pg0, runs migrations, creates pool."""
        from clarvis.vendor.hindsight.engine.memory_engine import MemoryEngine

        self._engine = MemoryEngine(db_url=self._db_url)
        await self._engine.initialize()
        self._ready = True
        logger.info("HindsightStore started (banks: %s)", ", ".join(self._banks))

    async def stop(self) -> None:
        """Shut down the MemoryEngine and release resources."""
        if self._engine is not None:
            await self._engine.close()
            self._engine = None
        self._ready = False
        logger.info("HindsightStore stopped")

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def engine(self) -> Any:
        """Direct engine access for advanced use cases."""
        return self._engine

    # ── Helpers ────────────────────────────────────────────────────

    def _validate_bank(self, bank: str) -> None:
        if bank not in self._banks:
            raise ValueError(f"Unknown bank '{bank}'. Available: {', '.join(self._banks)}")

    def _rc(self):
        """Build an internal RequestContext (skips tenant auth)."""
        from clarvis.vendor.hindsight.models import RequestContext

        return RequestContext(internal=True)

    def visible_banks(self, visibility: str = "master") -> list[str]:
        """Return bank names accessible at the given visibility level."""
        if visibility == "master":
            return list(self._banks)
        return [
            name
            for name, cfg in self._banks.items()
            if cfg.get("visibility") == visibility or cfg.get("visibility") == "all"
        ]

    def default_bank(self, visibility: str = "master") -> str:
        """Return first visible bank for this visibility level."""
        banks = self.visible_banks(visibility)
        if not banks:
            raise ValueError(f"No banks visible at level '{visibility}'")
        return banks[0]

    # ── Fact Operations ────────────────────────────────────────────

    async def store_facts(
        self,
        facts: list,
        bank: str = "parletre",
    ) -> list[str]:
        """Store pre-structured facts via retain_direct (Level 2).

        Args:
            facts: List of FactInput objects.
            bank: Bank name.

        Returns:
            List of created fact IDs (UUID strings).
        """
        self._validate_bank(bank)
        return await self._engine.retain_direct_async(bank_id=bank, facts=facts, request_context=self._rc())

    async def delete_fact(self, fact_id: str) -> dict:
        """Delete a fact and its associated links/observations."""
        return await self._engine.delete_memory_unit(fact_id, request_context=self._rc())

    async def update_fact(
        self,
        fact_id: str,
        *,
        bank: str = "parletre",
        content: str | None = None,
        fact_type: str | None = None,
        confidence: float | None = None,
        entities: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Update a fact by delete-and-re-retain.

        MemoryEngine doesn't support atomic fact updates. This deletes
        the old fact and creates a new one via retain_direct.

        Returns:
            Dict with old_id, new_ids, and status.
        """
        self._validate_bank(bank)
        rc = self._rc()

        if content is None:
            return {"success": False, "message": "content is required for update"}

        # Get old fact for defaults
        old = await self._engine.get_memory_unit(bank, fact_id, request_context=rc)

        # Delete old
        await self._engine.delete_memory_unit(fact_id, request_context=rc)

        # Build new FactInput
        from clarvis.vendor.hindsight.engine.retain.types import FactInput

        new_fact = FactInput(
            fact_text=content,
            fact_type=fact_type or (old.get("fact_type") if old else "world"),
            entities=entities if entities is not None else (old.get("entities") if old else []) or [],
            confidence=confidence if confidence is not None else (old.get("confidence") if old else None),
            tags=tags or (old.get("tags") if old else []) or [],
            document_id=old.get("document_id") if old else None,
        )

        new_ids = await self._engine.retain_direct_async(bank_id=bank, facts=[new_fact], request_context=rc)

        return {"success": True, "old_id": fact_id, "new_ids": new_ids}

    async def list_facts(
        self,
        bank: str = "parletre",
        *,
        fact_type: str | None = None,
        search_query: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
        tags: list[str] | None = None,
    ) -> dict:
        """List facts with optional filtering."""
        self._validate_bank(bank)
        return await self._engine.list_memory_units(
            bank,
            fact_type=fact_type,
            search_query=search_query,
            since=since,
            limit=limit,
            offset=offset,
            request_context=self._rc(),
        )

    async def get_fact(self, bank: str, fact_id: str) -> dict | None:
        """Get a single fact by ID."""
        self._validate_bank(bank)
        return await self._engine.get_memory_unit(bank, fact_id, request_context=self._rc())

    # ── Retrieval (Non-LLM) ───────────────────────────────────────

    async def recall(
        self,
        query: str,
        bank: str = "parletre",
        *,
        max_tokens: int = 4096,
        fact_type: list[str] | None = None,
        include_chunks: bool = False,
        include_entities: bool = False,
        tags: list[str] | None = None,
        tags_match: str = "any",
    ) -> dict:
        """TEMPR retrieval — semantic + BM25 + graph + temporal fusion.

        Returns:
            RecallResult as dict with results, entities, chunks.
        """
        self._validate_bank(bank)
        result = await self._engine.recall_async(
            bank,
            query,
            max_tokens=max_tokens,
            fact_type=fact_type,
            include_chunks=include_chunks,
            include_entities=include_entities,
            tags=tags,
            tags_match=tags_match,
            request_context=self._rc(),
        )
        return result.model_dump() if hasattr(result, "model_dump") else result

    async def search_mental_models(
        self,
        query: str,
        bank: str = "parletre",
        *,
        max_results: int = 5,
        tags: list[str] | None = None,
        tags_match: str = "any",
    ) -> dict:
        """Semantic search over mental models (pgvector similarity)."""
        self._validate_bank(bank)
        return await self._engine.search_mental_models_async(
            bank,
            query,
            max_results=max_results,
            tags=tags,
            tags_match=tags_match,
            request_context=self._rc(),
        )

    async def search_observations(
        self,
        query: str,
        bank: str = "parletre",
        *,
        max_tokens: int = 5000,
        tags: list[str] | None = None,
        tags_match: str = "any",
    ) -> dict:
        """Search observations with staleness info."""
        self._validate_bank(bank)
        return await self._engine.search_observations_async(
            bank,
            query,
            max_tokens=max_tokens,
            tags=tags,
            tags_match=tags_match,
            request_context=self._rc(),
        )

    async def expand(
        self,
        memory_ids: list[str],
        bank: str = "parletre",
        *,
        depth: str = "chunk",
    ) -> dict:
        """Expand memory → chunk → document hierarchy."""
        self._validate_bank(bank)
        return await self._engine.expand_async(bank, memory_ids, depth=depth, request_context=self._rc())

    # ── Consolidation ─────────────────────────────────────────────

    async def get_unconsolidated(
        self,
        bank: str = "parletre",
        *,
        limit: int = 100,
    ) -> dict:
        """Fetch facts pending consolidation."""
        self._validate_bank(bank)
        return await self._engine.get_unconsolidated_async(bank, limit=limit, request_context=self._rc())

    async def get_related_observations(
        self,
        bank: str,
        fact_texts: list[str],
        fact_tags: list[list[str]],
    ) -> dict:
        """Find observations related to given fact texts."""
        self._validate_bank(bank)
        return await self._engine.get_related_observations_async(
            bank, fact_texts, fact_tags, request_context=self._rc()
        )

    async def apply_consolidation_decisions(
        self,
        bank: str,
        decisions: list,
        fact_ids_to_mark: list[str],
        *,
        related_observations: list | None = None,
    ) -> dict:
        """Apply agent-driven consolidation decisions.

        Security: update/delete validates observation_id against related_observations.
        """
        self._validate_bank(bank)
        return await self._engine.apply_consolidation_decisions_async(
            bank,
            decisions,
            fact_ids_to_mark,
            related_observations=related_observations,
            request_context=self._rc(),
        )

    # ── Mental Models ─────────────────────────────────────────────

    async def create_mental_model(
        self,
        bank: str,
        name: str,
        content: str,
        source_query: str,
        *,
        tags: list[str] | None = None,
        trigger: dict | None = None,
    ) -> dict:
        """Create a named mental model (curated summary)."""
        self._validate_bank(bank)
        return await self._engine.create_mental_model(
            bank,
            name,
            source_query,
            content,
            tags=tags,
            trigger=trigger,
            request_context=self._rc(),
        )

    async def update_mental_model(
        self,
        bank: str,
        model_id: str,
        *,
        content: str | None = None,
        name: str | None = None,
        source_query: str | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Update an existing mental model."""
        self._validate_bank(bank)
        return await self._engine.update_mental_model(
            bank,
            model_id,
            content=content,
            name=name,
            source_query=source_query,
            tags=tags,
            request_context=self._rc(),
        )

    async def list_mental_models(
        self,
        bank: str = "parletre",
        *,
        tags: list[str] | None = None,
        tags_match: str = "any",
        since: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """List mental models for a bank."""
        self._validate_bank(bank)
        return await self._engine.list_mental_models(
            bank,
            tags=tags,
            tags_match=tags_match,
            since=since,
            limit=limit,
            offset=offset,
            request_context=self._rc(),
        )

    async def get_mental_model(self, bank: str, model_id: str) -> dict | None:
        """Get a single mental model by ID."""
        self._validate_bank(bank)
        return await self._engine.get_mental_model(bank, model_id, request_context=self._rc())

    async def delete_mental_model(self, bank: str, model_id: str) -> dict:
        """Delete a mental model."""
        self._validate_bank(bank)
        return await self._engine.delete_mental_model(bank, model_id, request_context=self._rc())

    async def list_models_needing_refresh(
        self,
        bank: str = "parletre",
        *,
        tags: list[str] | None = None,
    ) -> list[dict]:
        """Find mental models that should be refreshed after consolidation."""
        self._validate_bank(bank)
        return await self._engine.list_models_needing_refresh_async(
            bank, consolidated_tags=tags, request_context=self._rc()
        )

    # ── Observations ──────────────────────────────────────────────

    async def list_observations(
        self,
        bank: str = "parletre",
        *,
        tags: list[str] | None = None,
        tags_match: str = "any",
        since: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """List consolidated observations."""
        self._validate_bank(bank)
        return await self._engine.list_mental_models_consolidated(
            bank,
            tags=tags,
            tags_match=tags_match,
            since=since,
            limit=limit,
            offset=offset,
            request_context=self._rc(),
        )

    async def get_observation(
        self,
        bank: str,
        observation_id: str,
        *,
        include_source_facts: bool = True,
    ) -> dict | None:
        """Get a single observation with optional source fact details."""
        self._validate_bank(bank)
        return await self._engine.get_observation_consolidated(
            bank,
            observation_id,
            include_source_memories=include_source_facts,
            request_context=self._rc(),
        )

    async def clear_observations(self, bank: str) -> dict:
        """Clear all observations for a bank (resets consolidation)."""
        self._validate_bank(bank)
        return await self._engine.clear_observations(bank, request_context=self._rc())

    # ── Directives ────────────────────────────────────────────────

    async def create_directive(
        self,
        bank: str,
        name: str,
        content: str,
        *,
        priority: int = 0,
        tags: list[str] | None = None,
        is_active: bool = True,
    ) -> dict:
        """Create a directive (hard rule injected into reasoning)."""
        self._validate_bank(bank)
        return await self._engine.create_directive(
            bank,
            name,
            content,
            priority=priority,
            is_active=is_active,
            tags=tags,
            request_context=self._rc(),
        )

    async def update_directive(
        self,
        bank: str,
        directive_id: str,
        *,
        content: str | None = None,
        priority: int | None = None,
        is_active: bool | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """Update an existing directive."""
        self._validate_bank(bank)
        kwargs: dict[str, Any] = {}
        if content is not None:
            kwargs["content"] = content
        if priority is not None:
            kwargs["priority"] = priority
        if is_active is not None:
            kwargs["is_active"] = is_active
        if tags is not None:
            kwargs["tags"] = tags
        return await self._engine.update_directive(bank, directive_id, **kwargs, request_context=self._rc())

    async def list_directives(
        self,
        bank: str = "parletre",
        *,
        tags: list[str] | None = None,
        active_only: bool = True,
        limit: int = 100,
    ) -> list[dict]:
        """List directives for a bank."""
        self._validate_bank(bank)
        return await self._engine.list_directives(
            bank,
            tags=tags,
            active_only=active_only,
            limit=limit,
            request_context=self._rc(),
        )

    async def delete_directive(self, bank: str, directive_id: str) -> dict:
        """Delete a directive."""
        self._validate_bank(bank)
        return await self._engine.delete_directive(bank, directive_id, request_context=self._rc())

    # ── Entities ──────────────────────────────────────────────────

    async def list_entities(
        self,
        bank: str = "parletre",
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        """List entities in a bank."""
        self._validate_bank(bank)
        return await self._engine.list_entities(bank, limit=limit, offset=offset, request_context=self._rc())

    async def get_entity(self, bank: str, entity_id: str) -> dict | None:
        """Get a single entity."""
        self._validate_bank(bank)
        return await self._engine.get_entity(bank, entity_id, request_context=self._rc())

    async def get_entity_state(self, bank: str, entity_id: str) -> dict:
        """Get entity state (facts + observations about this entity)."""
        self._validate_bank(bank)
        return await self._engine.get_entity_state(bank, entity_id, request_context=self._rc())

    # ── Bank Configuration ────────────────────────────────────────

    async def get_bank_profile(self, bank: str) -> dict:
        """Get bank profile — name, disposition, mission."""
        self._validate_bank(bank)
        return await self._engine.get_bank_profile(bank, request_context=self._rc())

    async def set_bank_mission(self, bank: str, mission: str) -> None:
        """Set the mission text for a bank."""
        self._validate_bank(bank)
        await self._engine.set_bank_mission(bank, mission, request_context=self._rc())

    async def update_bank_disposition(
        self,
        bank: str,
        *,
        skepticism: int | None = None,
        literalism: int | None = None,
        empathy: int | None = None,
    ) -> None:
        """Tune per-bank personality: skepticism, literalism, empathy (1-5)."""
        self._validate_bank(bank)
        kwargs: dict[str, Any] = {}
        if skepticism is not None:
            kwargs["skepticism"] = skepticism
        if literalism is not None:
            kwargs["literalism"] = literalism
        if empathy is not None:
            kwargs["empathy"] = empathy
        await self._engine.update_bank_disposition(bank, **kwargs, request_context=self._rc())

    # ── Tags & Stats ──────────────────────────────────────────────

    async def list_tags(self, bank: str = "parletre") -> list:
        """List all tags used in a bank."""
        self._validate_bank(bank)
        return await self._engine.list_tags(bank, request_context=self._rc())

    async def get_bank_stats(self, bank: str = "parletre") -> dict:
        """Get bank statistics — counts, last_consolidated_at, pending_consolidation."""
        self._validate_bank(bank)
        return await self._engine.get_bank_stats(bank, request_context=self._rc())

    # ── Documents & Chunks ────────────────────────────────────────

    async def list_documents(self, bank: str = "parletre") -> dict:
        """List documents (provenance sources) in a bank."""
        self._validate_bank(bank)
        return await self._engine.list_documents(bank, request_context=self._rc())

    async def get_document(self, bank: str, document_id: str) -> dict | None:
        """Get a document by ID."""
        self._validate_bank(bank)
        return await self._engine.get_document(bank, document_id, request_context=self._rc())

    async def get_chunk(self, chunk_id: str) -> dict | None:
        """Get a raw chunk by ID."""
        return await self._engine.get_chunk(chunk_id, request_context=self._rc())

    async def delete_document(self, document_id: str) -> dict:
        """Delete a document and its associated chunks."""
        return await self._engine.delete_document(document_id, request_context=self._rc())
