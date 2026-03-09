"""MemoryStore — unified interface to Hindsight (conversational memory) and Cognee (knowledge graph).

Single class managing both engines with independent failure tolerance.
Hindsight methods keep their original names; Cognee methods are prefixed with ``kg_``.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── Local dataclasses (not in upstream hindsight_api 0.4.15) ───────────


@dataclass
class FactInput:
    """Pre-structured fact for retain_direct (bypasses LLM extraction)."""

    fact_text: str
    fact_type: str  # world, experience, opinion
    entities: list[str] = field(default_factory=list)
    occurred_start: datetime | None = None
    occurred_end: datetime | None = None
    context: str = ""
    confidence: float | None = None
    tags: list[str] = field(default_factory=list)
    document_id: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class ConsolidationDecision:
    """Agent-driven consolidation action."""

    action: str  # "create" | "update" | "delete"
    text: str
    source_fact_ids: list[str]
    observation_id: str | None = None


# ── Cognee formatting helpers ──────────────────────────────────────────


def _fmt_entities(entities: list[dict]) -> str:
    if not entities:
        return "No entities found."
    lines = []
    for i, e in enumerate(entities, 1):
        eid = str(e.get("id", "?"))[:12]
        name = e.get("name", "unnamed")
        etype = e.get("type", "")
        desc = e.get("description") or ""
        parts = [f"[{etype}]" if etype else "", name]
        if desc:
            preview = desc[:60] + ("..." if len(desc) > 60 else "")
            parts.append(f"-- {preview}")
        line = " ".join(p for p in parts if p)
        lines.append(f"  {i}. [id:{eid}] {line}")
    return "\n".join(lines)


def _fmt_relations(rels: list[dict]) -> str:
    if not rels:
        return "No relationships found."
    lines = []
    for i, r in enumerate(rels, 1):
        src = str(r.get("source_id", "?"))[:8]
        tgt = str(r.get("target_id", "?"))[:8]
        rel = r.get("relationship", "related_to")
        props = r.get("properties", {})
        prop_str = f" {props}" if props else ""
        lines.append(f"  {i}. [{src}] --{rel}--> [{tgt}]{prop_str}")
    return "\n".join(lines)


def _fmt_search_results(results: list[dict]) -> str:
    if not results:
        return "No results found."
    lines = []
    for i, r in enumerate(results, 1):
        content = r.get("result", str(r))
        ds_name = r.get("dataset_name", "")
        if isinstance(content, dict):
            content = json.dumps(content, default=str, ensure_ascii=False)
        elif isinstance(content, list):
            content = "; ".join(str(x) for x in content)
        suffix = f" [{ds_name}]" if ds_name else ""
        content = str(content)
        if len(content) > 300:
            content = content[:297] + "..."
        lines.append(f"  {i}.{suffix} {content}")
    return f"Results ({len(results)}):\n" + "\n".join(lines)


_SEARCH_TYPE_MAP: dict[str, Any] = {}  # populated lazily on first kg_search


def _get_search_type_map() -> dict[str, Any]:
    if not _SEARCH_TYPE_MAP:
        from cognee.api.v1.search import SearchType

        _SEARCH_TYPE_MAP.update(
            {
                "graph_completion": SearchType.GRAPH_COMPLETION,
                "chunks": SearchType.CHUNKS,
                "summaries": SearchType.SUMMARIES,
                "rag_completion": SearchType.RAG_COMPLETION,
                "graph_summary_completion": SearchType.GRAPH_SUMMARY_COMPLETION,
                "natural_language": SearchType.NATURAL_LANGUAGE,
                "triplet_completion": SearchType.TRIPLET_COMPLETION,
            }
        )
    return _SEARCH_TYPE_MAP


# ── MemoryStore ────────────────────────────────────────────────────────


class MemoryStore:
    """Unified memory interface — Hindsight (facts) + Cognee (knowledge graph).

    Either engine can fail independently; the other continues working.
    """

    def __init__(
        self,
        *,
        # Hindsight config
        db_url: str = "pg0",
        banks: dict[str, dict] | None = None,
        llm_provider: str = "anthropic",
        llm_model: str = "claude-sonnet-4-6",
        llm_api_key: str | None = None,
        # Cognee config
        kg_db_host: str = "localhost",
        kg_db_port: int = 5432,
        kg_db_name: str = "clarvis_knowledge",
        kg_db_username: str | None = None,
        kg_db_password: str = "",
        kg_graph_path: str | Path | None = None,
        kg_llm_provider: str = "anthropic",
        kg_llm_model: str = "claude-sonnet-4-6",
        kg_llm_api_key: str | None = None,
    ) -> None:
        # Hindsight
        self._db_url = db_url
        self._banks = banks or {
            "parletre": {"visibility": "master"},
            "agora": {"visibility": "all"},
        }
        self._llm_provider = llm_provider
        self._llm_model = llm_model
        self._llm_api_key = llm_api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._engine: Any = None
        self._facts_ready = False

        # Cognee
        self._kg_db_host = kg_db_host
        self._kg_db_port = kg_db_port
        self._kg_db_name = kg_db_name
        self._kg_db_username = kg_db_username or os.environ.get("USER", "")
        self._kg_db_password = kg_db_password
        from clarvis.core.paths import CLARVIS_HOME

        self._kg_graph_path = str(
            Path(kg_graph_path).expanduser() if kg_graph_path else CLARVIS_HOME / "memory" / "knowledge_graph_kuzu"
        )
        self._kg_llm_provider = kg_llm_provider
        self._kg_llm_model = kg_llm_model
        self._kg_llm_api_key = kg_llm_api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._kg_ready = False

    # ── Lifecycle ──────────────────────────────────────────────────

    async def start(self) -> None:
        """Start both engines. Either can fail independently."""
        # Hindsight
        try:
            from hindsight_api.engine.memory_engine import MemoryEngine

            self._engine = MemoryEngine(
                db_url=self._db_url,
                memory_llm_provider=self._llm_provider,
                memory_llm_model=self._llm_model,
                memory_llm_api_key=self._llm_api_key,
            )
            await self._engine.initialize()
            self._facts_ready = True
            logger.info("Hindsight started (banks: %s)", ", ".join(self._banks))
        except Exception:
            logger.exception("Failed to start Hindsight engine")
            self._engine = None
            self._facts_ready = False

        # Cognee
        try:
            import cognee

            db_url = (
                f"postgresql://{self._kg_db_username}:{self._kg_db_password}"
                f"@{self._kg_db_host}:{self._kg_db_port}/{self._kg_db_name}"
            )
            cognee.config.set_relational_db_config(
                {
                    "db_provider": "postgres",
                    "db_host": self._kg_db_host,
                    "db_port": str(self._kg_db_port),
                    "db_name": self._kg_db_name,
                    "db_username": self._kg_db_username,
                    "db_password": self._kg_db_password,
                }
            )
            cognee.config.set_vector_db_config(
                {
                    "vector_db_provider": "pgvector",
                    "vector_db_url": db_url,
                }
            )
            cognee.config.set_graph_db_config(
                {
                    "graph_database_provider": "kuzu",
                    "graph_file_path": self._kg_graph_path,
                    "graph_filename": Path(self._kg_graph_path).name,
                }
            )
            cognee.config.set_llm_config(
                {
                    "llm_provider": self._kg_llm_provider,
                    "llm_model": self._kg_llm_model,
                    "llm_api_key": self._kg_llm_api_key,
                }
            )
            self._kg_ready = True
            logger.info(
                "Cognee started (graph=%s, db=%s/%s)",
                self._kg_graph_path,
                self._kg_db_host,
                self._kg_db_name,
            )
        except Exception:
            logger.exception("Failed to start Cognee backend")
            self._kg_ready = False

    async def stop(self) -> None:
        if self._engine is not None:
            await self._engine.close()
            self._engine = None
        self._facts_ready = False
        self._kg_ready = False
        logger.info("MemoryStore stopped")

    @property
    def ready(self) -> bool:
        return self._facts_ready or self._kg_ready

    @property
    def facts_ready(self) -> bool:
        return self._facts_ready

    @property
    def kg_ready(self) -> bool:
        return self._kg_ready

    @property
    def engine(self) -> Any:
        return self._engine

    # ── Helpers ────────────────────────────────────────────────────

    def _validate_bank(self, bank: str) -> None:
        if bank not in self._banks:
            raise ValueError(f"Unknown bank '{bank}'. Available: {', '.join(self._banks)}")

    def _rc(self):
        from hindsight_api.models import RequestContext

        return RequestContext(internal=True)

    async def _pending_consolidation_count(self, bank: str) -> int:
        """Count facts pending consolidation (shared by search methods)."""
        from hindsight_api.engine.db_utils import acquire_with_retry
        from hindsight_api.engine.memory_engine import fq_table

        pool = await self._engine._get_pool()
        async with acquire_with_retry(pool) as conn:
            return await conn.fetchval(
                f"SELECT COUNT(*) FROM {fq_table('memory_units')} "
                f"WHERE bank_id = $1 AND consolidated_at IS NULL "
                f"AND fact_type IN ('experience', 'world')",
                bank,
            )

    def visible_banks(self, visibility: str = "master") -> list[str]:
        if visibility == "master":
            return list(self._banks)
        return [
            name
            for name, cfg in self._banks.items()
            if cfg.get("visibility") == visibility or cfg.get("visibility") == "all"
        ]

    def default_bank(self, visibility: str = "master") -> str:
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
        """Store pre-structured facts via retain_direct (no LLM extraction)."""
        self._validate_bank(bank)
        return await self._retain_direct(bank, facts)

    async def _retain_direct(self, bank_id: str, facts: list[FactInput]) -> list[str]:
        """retain_direct implementation using upstream hindsight_api 0.4.15 building blocks."""
        if not facts:
            return []

        from datetime import UTC
        from datetime import datetime as dt

        from hindsight_api.engine.db_utils import acquire_with_retry
        from hindsight_api.engine.retain import embedding_processing, entity_processing, fact_storage, link_creation
        from hindsight_api.engine.retain.types import EntityRef, ProcessedFact

        now = dt.now(UTC)
        pool = await self._engine._get_pool()

        # Convert FactInput -> ProcessedFact with placeholder embeddings
        processed_facts: list[ProcessedFact] = []
        for fi in facts:
            entities = [EntityRef(name=name) for name in fi.entities]
            pf = ProcessedFact(
                fact_text=fi.fact_text,
                fact_type=fi.fact_type,
                embedding=[],
                occurred_start=fi.occurred_start,
                occurred_end=fi.occurred_end,
                mentioned_at=now,
                context=fi.context,
                metadata=fi.metadata,
                entities=entities,
                causal_relations=[],
                document_id=fi.document_id,
                tags=list(fi.tags),
            )
            processed_facts.append(pf)

        # Augment texts + generate embeddings
        augmented_texts = embedding_processing.augment_texts_with_dates(
            processed_facts, self._engine._format_readable_date
        )
        embeddings = await embedding_processing.generate_embeddings_batch(self._engine.embeddings, augmented_texts)
        for pf, emb in zip(processed_facts, embeddings):
            pf.embedding = emb

        # DB transaction: bank -> facts -> entities -> links
        async with acquire_with_retry(pool) as conn:
            async with conn.transaction():
                await fact_storage.ensure_bank_exists(conn, bank_id)

                # Document tracking for facts with document_id
                doc_ids_seen: set[str] = set()
                for pf in processed_facts:
                    if pf.document_id and pf.document_id not in doc_ids_seen:
                        doc_ids_seen.add(pf.document_id)
                        combined = "\n".join(f.fact_text for f in processed_facts if f.document_id == pf.document_id)
                        await fact_storage.handle_document_tracking(
                            conn,
                            bank_id,
                            pf.document_id,
                            combined,
                            is_first_batch=True,
                            retain_params={},
                            document_tags=list(pf.tags),
                        )

                # Insert facts
                unit_ids = await fact_storage.insert_facts_batch(conn, bank_id, processed_facts)

                # Process entities
                entity_links = await entity_processing.process_entities_batch(
                    self._engine.entity_resolver,
                    conn,
                    bank_id,
                    unit_ids,
                    processed_facts,
                    [],
                )

                # Create links
                await link_creation.create_temporal_links_batch(conn, bank_id, unit_ids)
                embeddings_for_links = [f.embedding for f in processed_facts]
                await link_creation.create_semantic_links_batch(conn, bank_id, unit_ids, embeddings_for_links)
                if entity_links:
                    await entity_processing.insert_entity_links_batch(conn, entity_links)
                await link_creation.create_causal_links_batch(conn, unit_ids, processed_facts)

        return unit_ids

    async def delete_fact(self, fact_id: str) -> dict:
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
        """Update a fact by delete-and-re-retain."""
        self._validate_bank(bank)
        rc = self._rc()

        if content is None:
            return {"success": False, "message": "content is required for update"}

        old = await self._engine.get_memory_unit(bank, fact_id, request_context=rc)
        await self._engine.delete_memory_unit(fact_id, request_context=rc)

        new_fact = FactInput(
            fact_text=content,
            fact_type=fact_type or (old.get("fact_type") if old else "world"),
            entities=entities if entities is not None else (old.get("entities") if old else []) or [],
            confidence=confidence if confidence is not None else (old.get("confidence") if old else None),
            tags=tags or (old.get("tags") if old else []) or [],
            document_id=old.get("document_id") if old else None,
        )

        new_ids = await self._retain_direct(bank, [new_fact])
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
        self._validate_bank(bank)
        return await self._engine.get_memory_unit(bank, fact_id, request_context=self._rc())

    # ── Retrieval ──────────────────────────────────────────────────

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
        """TEMPR retrieval -- semantic + BM25 + graph + temporal fusion."""
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

        from hindsight_api.engine.db_utils import acquire_with_retry
        from hindsight_api.engine.reflect.tools import tool_search_mental_models
        from hindsight_api.engine.retain import embedding_utils

        pool = await self._engine._get_pool()

        embeddings = await embedding_utils.generate_embeddings_batch(self._engine.embeddings, [query])
        query_embedding = embeddings[0]

        pending_consolidation = await self._pending_consolidation_count(bank)

        async with acquire_with_retry(pool) as conn:
            return await tool_search_mental_models(
                conn,
                bank,
                query,
                query_embedding,
                max_results=max_results,
                tags=tags,
                tags_match=tags_match,
                pending_consolidation=pending_consolidation,
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

        from hindsight_api.engine.reflect.tools import tool_search_observations

        pending_consolidation = await self._pending_consolidation_count(bank)

        return await tool_search_observations(
            self._engine,
            bank,
            query,
            self._rc(),
            max_tokens=max_tokens,
            tags=tags,
            tags_match=tags_match,
            pending_consolidation=pending_consolidation,
        )

    async def expand(
        self,
        memory_ids: list[str],
        bank: str = "parletre",
        *,
        depth: str = "chunk",
    ) -> dict:
        """Expand memory -> chunk -> document hierarchy."""
        self._validate_bank(bank)

        from hindsight_api.engine.db_utils import acquire_with_retry
        from hindsight_api.engine.reflect.tools import tool_expand

        pool = await self._engine._get_pool()
        async with acquire_with_retry(pool) as conn:
            return await tool_expand(conn, bank, memory_ids, depth)

    # ── Consolidation ─────────────────────────────────────────────

    async def get_unconsolidated(
        self,
        bank: str = "parletre",
        *,
        limit: int = 100,
    ) -> dict:
        """Fetch facts pending consolidation."""
        self._validate_bank(bank)

        from hindsight_api.engine.db_utils import acquire_with_retry
        from hindsight_api.engine.memory_engine import fq_table

        pool = await self._engine._get_pool()

        async with acquire_with_retry(pool) as conn:
            rows = await conn.fetch(
                f"""
                SELECT id, text, fact_type, occurred_start, occurred_end,
                       event_date, tags, mentioned_at
                FROM {fq_table("memory_units")}
                WHERE bank_id = $1
                  AND consolidated_at IS NULL
                  AND fact_type IN ('experience', 'world')
                ORDER BY created_at ASC
                LIMIT $2
                """,
                bank,
                limit,
            )
            total_count = await conn.fetchval(
                f"""
                SELECT COUNT(*)
                FROM {fq_table("memory_units")}
                WHERE bank_id = $1
                  AND consolidated_at IS NULL
                  AND fact_type IN ('experience', 'world')
                """,
                bank,
            )

        facts = []
        for row in rows:
            facts.append(
                {
                    "id": str(row["id"]),
                    "text": row["text"],
                    "fact_type": row["fact_type"],
                    "occurred_start": row["occurred_start"].isoformat() if row["occurred_start"] else None,
                    "occurred_end": row["occurred_end"].isoformat() if row["occurred_end"] else None,
                    "event_date": row["event_date"].isoformat() if row["event_date"] else None,
                    "tags": row["tags"] or [],
                    "mentioned_at": row["mentioned_at"].isoformat() if row["mentioned_at"] else None,
                }
            )

        return {"facts": facts, "total_count": total_count}

    async def get_related_observations(
        self,
        bank: str,
        fact_texts: list[str],
        fact_tags: list[list[str]],
    ) -> dict:
        """Find observations related to given fact texts."""
        import asyncio

        self._validate_bank(bank)

        from hindsight_api.engine.consolidation.consolidator import _find_related_observations

        rc = self._rc()
        recall_tasks = [
            _find_related_observations(
                memory_engine=self._engine,
                bank_id=bank,
                query=text,
                request_context=rc,
                tags=tags,
            )
            for text, tags in zip(fact_texts, fact_tags)
        ]
        per_fact_recalls = await asyncio.gather(*recall_tasks)

        per_fact_obs_ids: dict[str, list[str]] = {}
        for i, recall_result in enumerate(per_fact_recalls):
            per_fact_obs_ids[fact_texts[i]] = [str(obs.id) for obs in recall_result.results]

        seen_ids: set[str] = set()
        union_observations: list[Any] = []
        union_source_facts: dict[str, Any] = {}
        for recall_result in per_fact_recalls:
            for obs in recall_result.results:
                obs_id = str(obs.id)
                if obs_id not in seen_ids:
                    seen_ids.add(obs_id)
                    union_observations.append(obs)
            if recall_result.source_facts:
                union_source_facts.update(recall_result.source_facts)

        return {
            "observations": [obs.model_dump() for obs in union_observations],
            "source_facts": {k: v.model_dump() for k, v in union_source_facts.items()},
            "per_fact_obs_ids": per_fact_obs_ids,
        }

    async def apply_consolidation_decisions(
        self,
        bank: str,
        decisions: list,
        fact_ids_to_mark: list[str],
        *,
        related_observations: list | None = None,
    ) -> dict:
        """Apply agent-driven consolidation decisions."""
        import uuid as uuid_module

        self._validate_bank(bank)

        from hindsight_api.engine.consolidation.consolidator import (
            _execute_create_action,
            _execute_delete_action,
            _execute_update_action,
        )
        from hindsight_api.engine.db_utils import acquire_with_retry
        from hindsight_api.engine.memory_engine import fq_table

        pool = await self._engine._get_pool()

        # Build valid observation ID set for security validation
        valid_obs_ids: set[str] = set()
        obs_objects: list[Any] = []
        if related_observations:
            from hindsight_api.engine.response_models import MemoryFact

            for obs in related_observations:
                if isinstance(obs, dict):
                    obs_obj = MemoryFact(**obs)
                    obs_objects.append(obs_obj)
                    valid_obs_ids.add(str(obs_obj.id))
                else:
                    obs_objects.append(obs)
                    valid_obs_ids.add(str(obs.id))

        created = updated = deleted = 0

        async with acquire_with_retry(pool) as conn:
            for d in decisions:
                if d.action == "create":
                    source_uuids = [uuid_module.UUID(fid) for fid in d.source_fact_ids]
                    await _execute_create_action(
                        conn=conn,
                        memory_engine=self._engine,
                        bank_id=bank,
                        source_memory_ids=source_uuids,
                        text=d.text,
                    )
                    created += 1
                elif d.action == "update":
                    if not d.observation_id:
                        logger.warning("[CONSOLIDATION L2] Rejected update -- no observation_id")
                        continue
                    if d.observation_id not in valid_obs_ids:
                        logger.warning(
                            "[CONSOLIDATION L2] Rejected update -- observation %s not in related set", d.observation_id
                        )
                        continue
                    source_uuids = [uuid_module.UUID(fid) for fid in d.source_fact_ids]
                    await _execute_update_action(
                        conn=conn,
                        memory_engine=self._engine,
                        bank_id=bank,
                        source_memory_ids=source_uuids,
                        observation_id=d.observation_id,
                        new_text=d.text,
                        observations=obs_objects,
                    )
                    updated += 1
                elif d.action == "delete":
                    if not d.observation_id:
                        logger.warning("[CONSOLIDATION L2] Rejected delete -- no observation_id")
                        continue
                    if d.observation_id not in valid_obs_ids:
                        logger.warning(
                            "[CONSOLIDATION L2] Rejected delete -- observation %s not in related set", d.observation_id
                        )
                        continue
                    await _execute_delete_action(conn=conn, bank_id=bank, observation_id=d.observation_id)
                    deleted += 1

            # Mark facts as consolidated
            marked = 0
            for fact_id in fact_ids_to_mark:
                await conn.execute(
                    f"UPDATE {fq_table('memory_units')} SET consolidated_at = NOW() WHERE id = $1",
                    uuid_module.UUID(fact_id),
                )
                marked += 1

        return {"created": created, "updated": updated, "deleted": deleted, "marked": marked}

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
        self._validate_bank(bank)
        return await self._engine.get_mental_model(bank, model_id, request_context=self._rc())

    async def delete_mental_model(self, bank: str, model_id: str) -> dict:
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

        from hindsight_api.engine.db_utils import acquire_with_retry
        from hindsight_api.engine.memory_engine import fq_table

        pool = await self._engine._get_pool()

        async with acquire_with_retry(pool) as conn:
            if tags:
                rows = await conn.fetch(
                    f"""
                    SELECT id, name, tags, source_query, content
                    FROM {fq_table("mental_models")}
                    WHERE bank_id = $1
                      AND (trigger->>'refresh_after_consolidation')::boolean = true
                      AND (
                        (tags IS NOT NULL AND tags != '{{}}' AND tags && $2::varchar[])
                        OR (tags IS NULL OR tags = '{{}}')
                      )
                    """,
                    bank,
                    tags,
                )
            else:
                rows = await conn.fetch(
                    f"""
                    SELECT id, name, tags, source_query, content
                    FROM {fq_table("mental_models")}
                    WHERE bank_id = $1
                      AND (trigger->>'refresh_after_consolidation')::boolean = true
                      AND (tags IS NULL OR tags = '{{}}')
                    """,
                    bank,
                )

        return [
            {
                "id": str(row["id"]),
                "name": row["name"],
                "tags": row["tags"] or [],
                "source_query": row["source_query"],
                "content": row["content"],
            }
            for row in rows
        ]

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
        self._validate_bank(bank)
        return await self._engine.get_observation_consolidated(
            bank,
            observation_id,
            include_source_memories=include_source_facts,
            request_context=self._rc(),
        )

    async def clear_observations(self, bank: str) -> dict:
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
        self._validate_bank(bank)
        return await self._engine.list_directives(
            bank,
            tags=tags,
            active_only=active_only,
            limit=limit,
            request_context=self._rc(),
        )

    async def delete_directive(self, bank: str, directive_id: str) -> dict:
        self._validate_bank(bank)
        return await self._engine.delete_directive(bank, directive_id, request_context=self._rc())

    # ── Entities (Hindsight) ──────────────────────────────────────

    async def list_entities(
        self,
        bank: str = "parletre",
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        self._validate_bank(bank)
        return await self._engine.list_entities(bank, limit=limit, offset=offset, request_context=self._rc())

    async def get_entity(self, bank: str, entity_id: str) -> dict | None:
        self._validate_bank(bank)
        return await self._engine.get_entity(bank, entity_id, request_context=self._rc())

    async def get_entity_state(self, bank: str, entity_id: str) -> dict:
        self._validate_bank(bank)
        return await self._engine.get_entity_state(bank, entity_id, request_context=self._rc())

    # ── Bank Configuration ────────────────────────────────────────

    async def get_bank_profile(self, bank: str) -> dict:
        self._validate_bank(bank)
        return await self._engine.get_bank_profile(bank, request_context=self._rc())

    async def set_bank_mission(self, bank: str, mission: str) -> None:
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
        self._validate_bank(bank)
        return await self._engine.list_tags(bank, request_context=self._rc())

    async def get_bank_stats(self, bank: str = "parletre") -> dict:
        self._validate_bank(bank)
        return await self._engine.get_bank_stats(bank, request_context=self._rc())

    # ── Documents & Chunks ────────────────────────────────────────

    async def list_documents(self, bank: str = "parletre") -> dict:
        self._validate_bank(bank)
        return await self._engine.list_documents(bank, request_context=self._rc())

    async def get_document(self, bank: str, document_id: str) -> dict | None:
        self._validate_bank(bank)
        return await self._engine.get_document(bank, document_id, request_context=self._rc())

    async def get_chunk(self, chunk_id: str) -> dict | None:
        return await self._engine.get_chunk(chunk_id, request_context=self._rc())

    async def delete_document(self, document_id: str) -> dict:
        return await self._engine.delete_document(document_id, request_context=self._rc())

    # ── Knowledge Graph (Cognee) — kg_ prefixed ───────────────────

    async def kg_ingest(
        self,
        content_or_path: str,
        *,
        dataset: str = "knowledge",
        tags: list[str] | None = None,
        format: bool = False,
    ) -> dict[str, Any] | str:
        """Ingest content or file path through the cognee pipeline."""
        import cognee

        from .entity_types import ENTITY_TYPES

        await cognee.add(content_or_path, dataset_name=dataset)
        await cognee.cognify(
            datasets=[dataset],
            graph_model=list(ENTITY_TYPES.values()),
        )

        result = {"status": "ok", "dataset": dataset, "tags": tags or []}
        if format:
            tag_info = f", tags: {result['tags']}" if result["tags"] else ""
            return f"Ingested into '{dataset}' (status: ok{tag_info})"
        return result

    async def kg_search(
        self,
        query: str,
        *,
        search_type: str = "graph_completion",
        datasets: list[str] | None = None,
        top_k: int = 10,
        format: bool = False,
    ) -> list[dict[str, Any]] | str:
        """Search the knowledge graph."""
        import cognee

        st_map = _get_search_type_map()
        from cognee.api.v1.search import SearchType

        st = st_map.get(search_type, SearchType.GRAPH_COMPLETION)
        kwargs: dict[str, Any] = {
            "query_text": query,
            "query_type": st,
            "top_k": top_k,
        }
        if datasets:
            kwargs["datasets"] = datasets

        results = await cognee.search(**kwargs)

        items = [
            {
                "result": r.search_result,
                "dataset_id": str(r.dataset_id) if r.dataset_id else None,
                "dataset_name": r.dataset_name,
            }
            for r in results
        ]
        return _fmt_search_results(items) if format else items

    async def kg_list_entities(
        self,
        *,
        type_name: str | None = None,
        name: str | None = None,
        format: bool = False,
    ) -> list[dict[str, Any]] | str:
        """List entities from the knowledge graph."""
        from cognee.infrastructure.databases.graph import get_graph_engine

        engine = await get_graph_engine()
        nodes_and_edges = await engine.get_graph_data()
        nodes = nodes_and_edges[0]

        results: list[dict[str, Any]] = []
        for node_id, props in nodes:
            if type_name and props.get("type") != type_name:
                continue
            if name and name.lower() not in (props.get("name") or "").lower():
                continue
            results.append({"id": str(node_id), **props})

        if format:
            if not results:
                return "No entities found."
            return f"Entities ({len(results)}):\n{_fmt_entities(results)}"
        return results

    async def kg_list_relations(
        self,
        *,
        entity_id: str | None = None,
        relationship_type: str | None = None,
        format: bool = False,
    ) -> list[dict[str, Any]] | str:
        """List relationships from the knowledge graph."""
        from cognee.infrastructure.databases.graph import get_graph_engine

        engine = await get_graph_engine()

        if entity_id:
            edges = await engine.get_edges(entity_id)
        else:
            _, edges = await engine.get_graph_data()

        results: list[dict[str, Any]] = []
        for edge in edges:
            source_id, target_id, rel_name, props = edge
            if relationship_type and rel_name != relationship_type:
                continue
            results.append(
                {
                    "source_id": str(source_id),
                    "target_id": str(target_id),
                    "relationship": rel_name,
                    "properties": props or {},
                }
            )

        if format:
            if not results:
                return "No relationships found."
            return f"Relationships ({len(results)}):\n{_fmt_relations(results)}"
        return results

    async def kg_update_entity(
        self,
        entity_id: str,
        fields: dict[str, Any],
        *,
        format: bool = False,
    ) -> dict[str, Any] | str:
        """Update properties on a graph node."""
        from cognee.infrastructure.databases.graph import get_graph_engine

        engine = await get_graph_engine()
        node = await engine.get_node(entity_id)
        if node is None:
            reason = f"entity {entity_id} not found"
            return f"Error: {reason}" if format else {"status": "error", "reason": reason}

        updated_props = {**node, **fields}
        edges = await engine.get_edges(entity_id)
        await engine.delete_node(entity_id)
        try:
            await engine.add_node(entity_id, properties=updated_props)
        except Exception:
            await engine.add_node(entity_id, properties=node)
            raise
        finally:
            for source_id, target_id, rel_name, props in edges:
                await engine.add_edge(str(source_id), str(target_id), rel_name, props)

        result = {"status": "ok", "entity_id": entity_id, "updated_fields": list(fields.keys())}
        if format:
            return f"Updated entity {entity_id[:12]}: {', '.join(result['updated_fields'])}"
        return result

    async def kg_merge_entities(
        self,
        entity_ids: list[str],
        *,
        format: bool = False,
    ) -> dict[str, Any] | str:
        """Merge multiple entities into one. First ID is the survivor."""
        if len(entity_ids) < 2:
            reason = "need at least 2 entity IDs to merge"
            return f"Error: {reason}" if format else {"status": "error", "reason": reason}

        from cognee.infrastructure.databases.graph import get_graph_engine

        engine = await get_graph_engine()
        survivor_id = entity_ids[0]

        for dup_id in entity_ids[1:]:
            edges = await engine.get_edges(dup_id)
            for source_id, target_id, rel_name, props in edges:
                new_source = survivor_id if str(source_id) == str(dup_id) else str(source_id)
                new_target = survivor_id if str(target_id) == str(dup_id) else str(target_id)
                if new_source == new_target:
                    continue
                await engine.add_edge(new_source, new_target, rel_name, props)
            await engine.delete_node(dup_id)

        result = {"status": "ok", "survivor_id": survivor_id, "merged_count": len(entity_ids) - 1}
        if format:
            return f"Merged {result['merged_count']} entities into {survivor_id[:12]}"
        return result

    async def kg_delete_entity(self, node_id: str, *, format: bool = False) -> dict[str, Any] | str:
        """Delete a node from the knowledge graph."""
        from cognee.infrastructure.databases.graph import get_graph_engine

        engine = await get_graph_engine()
        await engine.delete_node(node_id)
        result = {"status": "ok", "deleted_id": node_id}
        return f"Deleted: {node_id[:12]}" if format else result

    async def kg_build_communities(self, *, format: bool = False) -> dict[str, Any] | str:
        """Trigger community detection and summary building."""
        import cognee

        await cognee.memify()
        result = {"status": "ok", "action": "community_summaries_built"}
        return "Community summaries built (status: ok)" if format else result
