"""Memory MCP sub-server — Hindsight conversational memory via HindsightStore.

Exposes memory tools for the Hindsight backend (conversational memory with
facts, observations, mental models). Two backends, clear naming:

- **Hindsight** (this file): facts, observations, mental models.
  Tools use natural verbs: ``recall``, ``remember``, ``forget``.
- **Cognee** (knowledge_tools.py): document knowledge graph.
  Tools use ``knowledge`` prefix for search; direct verbs for mutations.

All tools return natural language strings for agent readability.
Bank access is controlled by the ``visibility`` parameter at server creation time.

IMPORTANT: Do NOT use ``from __future__ import annotations`` in this file.
It breaks Pydantic's runtime ``Annotated`` resolution for JSON schema generation.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastmcp import Context, FastMCP
from pydantic import Field

from ._helpers import make_lifespan

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────


def _get_store(ctx: Context):
    """Retrieve HindsightStore from lifespan context."""
    return ctx.fastmcp._lifespan_result["store"]


def _visibility(ctx: Context) -> str:
    return ctx.fastmcp._lifespan_result["visibility"]


def _fmt_facts(facts: list[dict]) -> str:
    """Format a list of fact dicts into numbered lines."""
    if not facts:
        return "No results."
    lines = []
    for i, fact in enumerate(facts, 1):
        fid = str(fact.get("id", "?"))[:12]
        ftype = fact.get("fact_type") or fact.get("type") or ""
        content = fact.get("content") or fact.get("text") or fact.get("fact_text") or str(fact)
        confidence = fact.get("confidence")
        tags = fact.get("tags")
        parts = [f"[{ftype}]" if ftype else "", content]
        if confidence is not None:
            parts.append(f"(confidence: {confidence})")
        if tags:
            parts.append(f"[tags: {', '.join(tags)}]")
        line = " ".join(p for p in parts if p)
        lines.append(f"  {i}. [id:{fid}] {line}")
    return "\n".join(lines)


def _fmt_mental_models(models: list[dict]) -> str:
    """Format mental models into numbered lines."""
    if not models:
        return "No mental models."
    lines = []
    for i, m in enumerate(models, 1):
        mid = str(m.get("id", "?"))[:12]
        name = m.get("name", "unnamed")
        tags = m.get("tags", [])
        content_preview = (m.get("content") or "")[:100]
        if len(m.get("content", "")) > 100:
            content_preview += "..."
        parts = [f"[id:{mid}]", name]
        if tags:
            parts.append(f"[tags: {', '.join(tags)}]")
        if content_preview:
            parts.append(f'-- "{content_preview}"')
        lines.append(f"  {i}. {' '.join(parts)}")
    return "\n".join(lines)


def _fmt_observations(observations: list[dict]) -> str:
    """Format observations into numbered lines."""
    if not observations:
        return "No observations."
    lines = []
    for i, obs in enumerate(observations, 1):
        oid = str(obs.get("id", "?"))[:12]
        content = (obs.get("content") or obs.get("summary") or "")[:120]
        if len(obs.get("content", obs.get("summary", ""))) > 120:
            content += "..."
        tags = obs.get("tags", [])
        parts = [f"[id:{oid}]", content]
        if tags:
            parts.append(f"[tags: {', '.join(tags)}]")
        lines.append(f"  {i}. {' '.join(parts)}")
    return "\n".join(lines)


# ── Server factory ────────────────────────────────────────────────────


def create_memory_server(daemon, visibility: str = "master") -> FastMCP:
    """Create the memory MCP sub-server (HindsightStore).

    Args:
        daemon: CentralHubDaemon instance.
        visibility: Access level for bank filtering.
            ``"master"`` sees all banks (parletre + agora).
            ``"all"`` sees only shared banks (agora).
    """
    # Get HindsightStore from daemon — prefer memory_store (Level 2),
    # fall back to hindsight_backend for backward compat during migration.
    store = getattr(daemon, "memory_store", None) or getattr(daemon, "hindsight_backend", None)

    server = FastMCP("Memory", lifespan=make_lifespan(daemon, visibility=visibility, store=store))

    # ── recall (available to all visibility levels) ───────────────

    @server.tool()
    async def recall(
        query: Annotated[
            str,
            Field(description="Natural language query to search conversational memory."),
        ],
        fact_type: Annotated[
            str | None,
            Field(
                description=(
                    "Filter by fact type: 'world' (objective facts), 'experience' "
                    "(first-person interactions), 'observation' (consolidated entity summaries), "
                    "'opinion' (beliefs with confidence). None returns all types."
                ),
            ),
        ] = None,
        tags: Annotated[
            list[str] | None,
            Field(description="Filter results by tags. None returns all."),
        ] = None,
        bank: Annotated[
            str | None,
            Field(
                description=(
                    "Memory bank to search. 'parletre' = personal memory (Clarvis only). "
                    "'agora' = shared knowledge (all agents). "
                    "Defaults to first visible bank for your access level."
                ),
            ),
        ] = None,
        ctx: Context = None,
    ) -> str:
        """Search conversational memory using semantic + temporal retrieval.

        Returns ranked memory facts matching the query, with IDs and types.
        Uses Hindsight's TEMPR retrieval (semantic + BM25 + graph + temporal
        fusion with cross-encoder reranking).
        """
        s = _get_store(ctx)
        if s is None or not s.ready:
            return "Error: Memory service not available."

        vis = _visibility(ctx)
        allowed = s.visible_banks(vis)
        resolved_bank = bank or s.default_bank(vis)
        if resolved_bank not in allowed:
            return f"Error: Bank '{resolved_bank}' not accessible. Available: {', '.join(allowed)}"

        fact_types = [fact_type] if fact_type else None
        try:
            result = await s.recall(
                query,
                bank=resolved_bank,
                max_tokens=4096,
                fact_type=fact_types,
                tags=tags,
            )
        except Exception as exc:
            return f"Error: {exc}"

        results = result.get("results") or result.get("facts") or []
        if not results:
            return "No memories found."

        return f"Results:\n{_fmt_facts(results)}"

    # ── Clarvis-only tools (not available to Factoria) ────────────────

    if visibility == "master":

        @server.tool()
        async def remember(
            content: Annotated[
                str,
                Field(description="Text content to store as a memory fact."),
            ],
            fact_type: Annotated[
                str,
                Field(
                    description=(
                        "Fact classification: 'world' (objective facts), 'experience' "
                        "(first-person interactions), or 'opinion' (beliefs with confidence)."
                    ),
                ),
            ] = "world",
            entities: Annotated[
                list[str] | None,
                Field(
                    description="Named entities mentioned in the fact (people, places, projects). Aids retrieval.",
                ),
            ] = None,
            confidence: Annotated[
                float | None,
                Field(
                    description="Confidence score for opinion facts (0.0-1.0). Ignored for non-opinion types.",
                ),
            ] = None,
            tags: Annotated[
                list[str] | None,
                Field(description="Tags for categorization and filtered retrieval."),
            ] = None,
            bank: Annotated[
                str | None,
                Field(description="Target bank. Defaults to first visible bank."),
            ] = None,
            ctx: Context = None,
        ) -> str:
            """Store a fact in conversational memory.

            Constructs a FactInput and calls store.store_facts(). The agent is
            responsible for entity identification, fact classification, temporal
            parsing, and confidence scoring.

            Returns the IDs of created memory facts.
            """
            s = _get_store(ctx)
            if s is None or not s.ready:
                return "Error: Memory service not available."

            vis = _visibility(ctx)
            resolved_bank = bank or s.default_bank(vis)

            from clarvis.vendor.hindsight.engine.retain.types import FactInput

            fact = FactInput(
                fact_text=content,
                fact_type=fact_type,
                entities=entities or [],
                confidence=confidence,
                tags=tags or [],
            )

            try:
                fact_ids = await s.store_facts([fact], bank=resolved_bank)
            except Exception as exc:
                return f"Error: {exc}"

            if not fact_ids:
                return "Stored (no fact IDs returned)."

            lines = [f"  [{fact_type}] id:{str(fid)[:12]}" for fid in fact_ids]
            return "Stored:\n" + "\n".join(lines)

        @server.tool()
        async def update_fact(
            fact_id: Annotated[
                str,
                Field(description="ID of the memory fact to update (from recall or list_facts results)."),
            ],
            content: Annotated[
                str | None,
                Field(description="New content text (replaces existing). Required."),
            ] = None,
            confidence: Annotated[
                float | None,
                Field(description="New confidence score (0.0-1.0)."),
            ] = None,
            fact_type: Annotated[
                str | None,
                Field(description="New fact type classification."),
            ] = None,
            bank: Annotated[
                str | None,
                Field(description="Bank containing the fact. Defaults to first visible bank."),
            ] = None,
            ctx: Context = None,
        ) -> str:
            """Update an existing memory fact.

            Requires ``content`` — the store deletes the old fact and creates a new
            one. Use ``recall`` or ``list_facts`` first to find the fact ID.
            """
            s = _get_store(ctx)
            if s is None or not s.ready:
                return "Error: Memory service not available."

            if content is None:
                return "Error: content is required for update."

            vis = _visibility(ctx)
            resolved_bank = bank or s.default_bank(vis)

            try:
                result = await s.update_fact(
                    fact_id,
                    bank=resolved_bank,
                    content=content,
                    confidence=confidence,
                    fact_type=fact_type,
                )
            except Exception as exc:
                return f"Error: {exc}"

            if result.get("success"):
                new_ids = result.get("new_ids", [])
                return f"Updated. Old: {fact_id[:12]}, New: {', '.join(str(i)[:12] for i in new_ids)}"
            return f"Update failed: {result.get('message', 'unknown error')}"

        @server.tool()
        async def forget(
            fact_id: Annotated[
                str,
                Field(description="ID of the memory fact to delete (from recall or list_facts results)."),
            ],
            ctx: Context = None,
        ) -> str:
            """Delete a memory fact by ID.

            Use ``recall`` or ``list_facts`` first to find the fact ID.
            This permanently removes the fact from storage.
            """
            s = _get_store(ctx)
            if s is None or not s.ready:
                return "Error: Memory service not available."

            try:
                await s.delete_fact(fact_id)
            except Exception as exc:
                return f"Error: {exc}"

            return f"Forgotten: {fact_id[:12]}"

        @server.tool()
        async def list_facts(
            fact_type: Annotated[
                str | None,
                Field(
                    description="Filter by type: 'world', 'experience', 'observation', 'opinion'. None returns all.",
                ),
            ] = None,
            limit: Annotated[
                int,
                Field(description="Maximum number of facts to return (default 50)."),
            ] = 50,
            bank: Annotated[
                str | None,
                Field(description="Bank to list from. Defaults to first visible bank."),
            ] = None,
            ctx: Context = None,
        ) -> str:
            """Browse stored memory facts with optional filtering.

            Returns a numbered list of facts with IDs and types.
            Use this for auditing memory contents or finding facts to update/forget.
            """
            s = _get_store(ctx)
            if s is None or not s.ready:
                return "Error: Memory service not available."

            vis = _visibility(ctx)
            resolved_bank = bank or s.default_bank(vis)

            try:
                result = await s.list_facts(
                    resolved_bank,
                    fact_type=fact_type,
                    limit=limit,
                )
            except Exception as exc:
                return f"Error: {exc}"

            items = result.get("items", []) if isinstance(result, dict) else result
            if not items:
                return "No memories found."

            total = result.get("total", len(items)) if isinstance(result, dict) else len(items)
            header = f"Showing {len(items)} of {total} facts"
            if fact_type:
                header += f" (type: {fact_type})"
            return f"{header}:\n{_fmt_facts(items)}"

        # ── Mental Model Tools ────────────────────────────────────────

        @server.tool()
        async def list_models(
            bank: Annotated[
                str | None,
                Field(description="Bank to list models from. Defaults to first visible bank."),
            ] = None,
            ctx: Context = None,
        ) -> str:
            """List mental models (curated summaries) in a bank.

            Mental models are named, structured summaries built from memory facts.
            Returns model IDs, names, tags, and content previews.
            """
            s = _get_store(ctx)
            if s is None or not s.ready:
                return "Error: Memory service not available."

            vis = _visibility(ctx)
            resolved_bank = bank or s.default_bank(vis)

            try:
                models = await s.list_mental_models(resolved_bank)
            except Exception as exc:
                return f"Error: {exc}"

            if not models:
                return "No mental models."
            return f"Mental models ({len(models)}):\n{_fmt_mental_models(models)}"

        @server.tool()
        async def search_models(
            query: Annotated[
                str,
                Field(description="Natural language query to search mental models."),
            ],
            tags: Annotated[
                list[str] | None,
                Field(description="Filter by tags. None searches all."),
            ] = None,
            bank: Annotated[
                str | None,
                Field(description="Bank to search. Defaults to first visible bank."),
            ] = None,
            ctx: Context = None,
        ) -> str:
            """Search mental models by semantic similarity.

            Returns models matching the query, ranked by relevance.
            Use ``list_models`` for a full inventory instead.
            """
            s = _get_store(ctx)
            if s is None or not s.ready:
                return "Error: Memory service not available."

            vis = _visibility(ctx)
            resolved_bank = bank or s.default_bank(vis)

            try:
                result = await s.search_mental_models(
                    query,
                    bank=resolved_bank,
                    tags=tags,
                )
            except Exception as exc:
                return f"Error: {exc}"

            models = result.get("results", []) if isinstance(result, dict) else result
            if not models:
                return "No matching mental models."
            return f"Matching models ({len(models)}):\n{_fmt_mental_models(models)}"

        @server.tool()
        async def create_model(
            name: Annotated[
                str,
                Field(description="Name for the mental model (e.g. 'Music Preferences', 'Work Context')."),
            ],
            content: Annotated[
                str,
                Field(description="Full content/summary text of the mental model."),
            ],
            source_query: Annotated[
                str,
                Field(description="Query that was used to gather the source facts for this model."),
            ],
            tags: Annotated[
                list[str] | None,
                Field(description="Tags for categorization."),
            ] = None,
            bank: Annotated[
                str | None,
                Field(description="Target bank. Defaults to first visible bank."),
            ] = None,
            ctx: Context = None,
        ) -> str:
            """Create a new mental model (curated summary).

            Mental models are named summaries built from memory facts. They persist
            across consolidation cycles and can be refreshed when new facts arrive.
            """
            s = _get_store(ctx)
            if s is None or not s.ready:
                return "Error: Memory service not available."

            vis = _visibility(ctx)
            resolved_bank = bank or s.default_bank(vis)

            try:
                result = await s.create_mental_model(
                    resolved_bank,
                    name,
                    content,
                    source_query,
                    tags=tags,
                )
            except Exception as exc:
                return f"Error: {exc}"

            mid = str(result.get("id", "?"))[:12]
            return f"Created mental model '{name}' [id:{mid}]"

        @server.tool()
        async def update_model(
            id: Annotated[
                str,
                Field(description="ID of the mental model to update (from list_models output)."),
            ],
            content: Annotated[
                str | None,
                Field(description="New content/summary text."),
            ] = None,
            name: Annotated[
                str | None,
                Field(description="New name."),
            ] = None,
            bank: Annotated[
                str | None,
                Field(description="Bank containing the model. Defaults to first visible bank."),
            ] = None,
            ctx: Context = None,
        ) -> str:
            """Update an existing mental model.

            Use ``list_models`` first to find the model ID.
            """
            s = _get_store(ctx)
            if s is None or not s.ready:
                return "Error: Memory service not available."

            vis = _visibility(ctx)
            resolved_bank = bank or s.default_bank(vis)

            try:
                await s.update_mental_model(
                    resolved_bank,
                    id,
                    content=content,
                    name=name,
                )
            except Exception as exc:
                return f"Error: {exc}"

            return f"Updated mental model [id:{id[:12]}]"

        @server.tool()
        async def delete_model(
            id: Annotated[
                str,
                Field(description="ID of the mental model to delete (from list_models output)."),
            ],
            bank: Annotated[
                str | None,
                Field(description="Bank containing the model. Defaults to first visible bank."),
            ] = None,
            ctx: Context = None,
        ) -> str:
            """Delete a mental model by ID.

            Use ``list_models`` first to find the model ID.
            """
            s = _get_store(ctx)
            if s is None or not s.ready:
                return "Error: Memory service not available."

            vis = _visibility(ctx)
            resolved_bank = bank or s.default_bank(vis)

            try:
                await s.delete_mental_model(resolved_bank, id)
            except Exception as exc:
                return f"Error: {exc}"

            return f"Deleted mental model [id:{id[:12]}]"

        # ── Observation + Audit Tools ─────────────────────────────────

        @server.tool()
        async def list_observations(
            limit: Annotated[
                int,
                Field(description="Maximum number of observations to return (default 50)."),
            ] = 50,
            bank: Annotated[
                str | None,
                Field(description="Bank to list observations from. Defaults to first visible bank."),
            ] = None,
            ctx: Context = None,
        ) -> str:
            """List consolidated observations.

            Observations are higher-level summaries produced by consolidation
            from individual memory facts. Returns IDs, content previews, and tags.
            """
            s = _get_store(ctx)
            if s is None or not s.ready:
                return "Error: Memory service not available."

            vis = _visibility(ctx)
            resolved_bank = bank or s.default_bank(vis)

            try:
                observations = await s.list_observations(resolved_bank, limit=limit)
            except Exception as exc:
                return f"Error: {exc}"

            if not observations:
                return "No observations."
            return f"Observations ({len(observations)}):\n{_fmt_observations(observations)}"

        @server.tool()
        async def get_observation(
            id: Annotated[
                str,
                Field(description="ID of the observation to retrieve (from list_observations output)."),
            ],
            include_sources: Annotated[
                bool,
                Field(description="Include the source facts that produced this observation."),
            ] = True,
            bank: Annotated[
                str | None,
                Field(description="Bank containing the observation. Defaults to first visible bank."),
            ] = None,
            ctx: Context = None,
        ) -> str:
            """Get a single observation with optional source fact details.

            Use ``list_observations`` first to find the observation ID.
            """
            s = _get_store(ctx)
            if s is None or not s.ready:
                return "Error: Memory service not available."

            vis = _visibility(ctx)
            resolved_bank = bank or s.default_bank(vis)

            try:
                obs = await s.get_observation(
                    resolved_bank,
                    id,
                    include_source_facts=include_sources,
                )
            except Exception as exc:
                return f"Error: {exc}"

            if obs is None:
                return f"Observation {id[:12]} not found."

            content = obs.get("content") or obs.get("summary") or ""
            tags = obs.get("tags", [])
            parts = [f"Observation [id:{id[:12]}]:", content]
            if tags:
                parts.append(f"Tags: {', '.join(tags)}")

            source_facts = obs.get("source_facts") or obs.get("source_memories") or []
            if source_facts:
                parts.append(f"\nSource facts ({len(source_facts)}):")
                parts.append(_fmt_facts(source_facts))

            return "\n".join(parts)

        @server.tool()
        async def audit(
            bank: Annotated[
                str | None,
                Field(description="Bank to audit. Defaults to first visible bank."),
            ] = None,
            ctx: Context = None,
        ) -> str:
            """Audit recent memory activity — facts, observations, and mental models.

            Returns items modified since the last check-in (from ContextAccumulator),
            capped at ~30 items per category. Useful for check-ins and reviewing
            memory drift.
            """
            s = _get_store(ctx)
            if s is None or not s.ready:
                return "Error: Memory service not available."

            vis = _visibility(ctx)
            resolved_bank = bank or s.default_bank(vis)

            # Read last check-in time from ContextAccumulator if available
            daemon_ref = ctx.fastmcp._lifespan_result.get("daemon")
            accumulator = getattr(daemon_ref, "context_accumulator", None) if daemon_ref else None
            if accumulator:
                pending = accumulator.get_pending()
                last_checkin = pending.get("last_check_in")
                if last_checkin:
                    try:
                        since_dt = datetime.fromisoformat(last_checkin)
                    except ValueError:
                        since_dt = datetime.now(timezone.utc) - timedelta(days=1)
                else:
                    since_dt = datetime.now(timezone.utc) - timedelta(days=1)
            else:
                since_dt = datetime.now(timezone.utc) - timedelta(days=1)

            cap = 30
            parts = []

            try:
                facts_result = await s.list_facts(resolved_bank, limit=cap * 3)
                facts = facts_result.get("items", []) if isinstance(facts_result, dict) else facts_result
                recent_facts = [f for f in facts if _is_after(f, since_dt)][:cap]
                parts.append(f"Facts since {since_dt.isoformat()} ({len(recent_facts)}):")
                if recent_facts:
                    parts.append(_fmt_facts(recent_facts))
                else:
                    parts.append("  (none)")
            except Exception as exc:
                parts.append(f"Facts: Error — {exc}")

            try:
                observations = await s.list_observations(resolved_bank, limit=cap * 3)
                recent_obs = [o for o in observations if _is_after(o, since_dt)][:cap]
                parts.append(f"\nObservations since {since_dt.isoformat()} ({len(recent_obs)}):")
                if recent_obs:
                    parts.append(_fmt_observations(recent_obs))
                else:
                    parts.append("  (none)")
            except Exception as exc:
                parts.append(f"\nObservations: Error — {exc}")

            try:
                models = await s.list_mental_models(resolved_bank)
                recent_models = [m for m in models if _is_after(m, since_dt)][:cap]
                parts.append(f"\nMental models since {since_dt.isoformat()} ({len(recent_models)}):")
                if recent_models:
                    parts.append(_fmt_mental_models(recent_models))
                else:
                    parts.append("  (none)")
            except Exception as exc:
                parts.append(f"\nMental models: Error — {exc}")

            return "\n".join(parts)

        @server.tool()
        async def stats(
            bank: Annotated[
                str | None,
                Field(description="Bank to get stats for. Defaults to first visible bank."),
            ] = None,
            ctx: Context = None,
        ) -> str:
            """Get bank statistics — fact counts, pending consolidation, etc.

            Returns counts of facts, observations, mental models, and consolidation status.
            """
            s = _get_store(ctx)
            if s is None or not s.ready:
                return "Error: Memory service not available."

            vis = _visibility(ctx)
            resolved_bank = bank or s.default_bank(vis)

            try:
                bank_stats = await s.get_bank_stats(resolved_bank)
            except Exception as exc:
                return f"Error: {exc}"

            if not bank_stats:
                return f"No stats available for bank '{resolved_bank}'."

            lines = [f"Bank '{resolved_bank}' stats:"]
            for key, value in bank_stats.items():
                lines.append(f"  {key}: {value}")
            return "\n".join(lines)

        # ── Consolidation Tools ──────────────────────────────────────────

        @server.tool()
        async def unconsolidated(
            limit: Annotated[
                int,
                Field(description="Max facts to return.", ge=1, le=500),
            ] = 100,
            bank: Annotated[
                str | None,
                Field(description="Bank to check. Defaults to first visible bank."),
            ] = None,
            ctx: Context = None,
        ) -> str:
            """List facts not yet processed by consolidation.

            Returns facts that haven't been consolidated into observations yet.
            Use this to identify facts that need grouping and synthesis.
            """
            s = _get_store(ctx)
            if s is None or not s.ready:
                return "Error: Memory service not available."

            vis = _visibility(ctx)
            resolved_bank = bank or s.default_bank(vis)

            try:
                result = await s.get_unconsolidated(resolved_bank, limit=limit)
            except Exception as exc:
                return f"Error: {exc}"

            facts = result.get("facts", []) if isinstance(result, dict) else []
            if not facts:
                return f"No unconsolidated facts in bank '{resolved_bank}'."

            return f"{len(facts)} unconsolidated facts:\n{_fmt_facts(facts)}"

        @server.tool()
        async def related_observations(
            fact_ids: Annotated[
                list[str],
                Field(description="List of fact IDs to find related observations for (from unconsolidated output)."),
            ],
            bank: Annotated[
                str | None,
                Field(description="Bank to search. Defaults to first visible bank."),
            ] = None,
            ctx: Context = None,
        ) -> str:
            """Find existing observations related to a set of facts.

            Accepts fact IDs (from ``unconsolidated`` output), looks up their texts
            and tags internally, then finds related observations. Use after
            ``unconsolidated`` to check which observations already cover the fact
            cluster before creating new ones.
            """
            s = _get_store(ctx)
            if s is None or not s.ready:
                return "Error: Memory service not available."

            vis = _visibility(ctx)
            resolved_bank = bank or s.default_bank(vis)

            # Resolve fact IDs to texts + tags for the store API
            fact_texts = []
            fact_tags = []
            for fid in fact_ids:
                try:
                    fact = await s.get_fact(resolved_bank, fid)
                except Exception:
                    fact = None
                if fact:
                    fact_texts.append(fact.get("content") or fact.get("text") or fact.get("fact_text") or "")
                    fact_tags.append(fact.get("tags") or [])
                else:
                    fact_texts.append("")
                    fact_tags.append([])

            try:
                result = await s.get_related_observations(resolved_bank, fact_texts, fact_tags)
            except Exception as exc:
                return f"Error: {exc}"

            observations = result.get("observations", []) if isinstance(result, dict) else []
            if not observations:
                return "No related observations found."

            return f"{len(observations)} related observations:\n{_fmt_observations(observations)}"

        @server.tool()
        async def consolidate(
            decisions: Annotated[
                list[dict],
                Field(
                    description=(
                        "List of consolidation decisions. Each dict has: "
                        '"action" ("create"|"update"|"delete"), '
                        '"text" (observation content), '
                        '"source_fact_ids" (list of fact ID strings), '
                        '"observation_id" (required for update/delete, null for create).'
                    ),
                ),
            ],
            fact_ids_to_mark: Annotated[
                list[str],
                Field(description="Fact IDs to mark as consolidated after applying decisions."),
            ],
            bank: Annotated[
                str | None,
                Field(description="Bank to operate on. Defaults to first visible bank."),
            ] = None,
            ctx: Context = None,
        ) -> str:
            """Apply consolidation decisions — create, update, or delete observations.

            Requires prior calls to ``unconsolidated`` and ``related_observations``
            to identify facts and existing observations. Decisions are applied atomically.
            """
            from clarvis.vendor.hindsight.engine.retain.types import ConsolidationDecision

            s = _get_store(ctx)
            if s is None or not s.ready:
                return "Error: Memory service not available."

            vis = _visibility(ctx)
            resolved_bank = bank or s.default_bank(vis)

            # Convert dicts to ConsolidationDecision objects
            try:
                parsed = [
                    ConsolidationDecision(
                        action=d["action"],
                        text=d.get("text", ""),
                        source_fact_ids=d.get("source_fact_ids", []),
                        observation_id=d.get("observation_id"),
                    )
                    for d in decisions
                ]
            except (KeyError, TypeError) as exc:
                return f"Error parsing decisions: {exc}"

            try:
                result = await s.apply_consolidation_decisions(resolved_bank, parsed, fact_ids_to_mark)
            except Exception as exc:
                return f"Error: {exc}"

            created = result.get("created", 0) if isinstance(result, dict) else 0
            updated = result.get("updated", 0) if isinstance(result, dict) else 0
            deleted = result.get("deleted", 0) if isinstance(result, dict) else 0
            marked = result.get("marked", 0) if isinstance(result, dict) else len(fact_ids_to_mark)
            return (
                f"Consolidation applied: {created} created, {updated} updated, "
                f"{deleted} deleted, {marked} facts marked as consolidated."
            )

        @server.tool()
        async def stale_models(
            bank: Annotated[
                str | None,
                Field(description="Bank to check. Defaults to first visible bank."),
            ] = None,
            ctx: Context = None,
        ) -> str:
            """List mental models that need refreshing due to new consolidated facts.

            Returns models whose tags overlap with recently consolidated observations,
            indicating they may be out of date. Use after ``consolidate``.
            """
            s = _get_store(ctx)
            if s is None or not s.ready:
                return "Error: Memory service not available."

            vis = _visibility(ctx)
            resolved_bank = bank or s.default_bank(vis)

            try:
                models = await s.list_models_needing_refresh(resolved_bank)
            except Exception as exc:
                return f"Error: {exc}"

            if not models:
                return "No mental models need refreshing."

            lines = [f"{len(models)} models need refreshing:"]
            for m in models:
                mid = str(m.get("id", "?"))[:12]
                name = m.get("name", "unnamed")
                tags = m.get("tags", [])
                tag_str = f" [tags: {', '.join(tags)}]" if tags else ""
                lines.append(f"  - [id:{mid}] {name}{tag_str}")
            return "\n".join(lines)

        # ── Directive Tools ──────────────────────────────────────────────

        @server.tool()
        async def list_directives(
            active_only: Annotated[
                bool,
                Field(description="Only return active directives (default True)."),
            ] = True,
            tags: Annotated[
                list[str] | None,
                Field(description="Filter by tags. None returns all."),
            ] = None,
            bank: Annotated[
                str | None,
                Field(description="Bank to list from. Defaults to first visible bank."),
            ] = None,
            ctx: Context = None,
        ) -> str:
            """Browse directives (hard rules injected into reasoning).

            Returns directive IDs, names, content, priority, and active status.
            Use this to review existing rules before creating or updating.
            """
            s = _get_store(ctx)
            if s is None or not s.ready:
                return "Error: Memory service not available."

            vis = _visibility(ctx)
            resolved_bank = bank or s.default_bank(vis)

            try:
                directives = await s.list_directives(
                    resolved_bank,
                    tags=tags,
                    active_only=active_only,
                )
            except Exception as exc:
                return f"Error: {exc}"

            if not directives:
                return "No directives found."

            lines = [f"Directives ({len(directives)}):"]
            for d in directives:
                did = str(d.get("id", "?"))[:12]
                name = d.get("name", "unnamed")
                content = d.get("content", "")
                priority = d.get("priority", 0)
                active = d.get("is_active", True)
                status = "active" if active else "inactive"
                preview = content[:120] + "..." if len(content) > 120 else content
                lines.append(f"  [{status}] [id:{did}] (p{priority}) {name}: {preview}")
            return "\n".join(lines)

        @server.tool()
        async def create_directive(
            name: Annotated[
                str,
                Field(description="Short name for the directive (e.g. 'No hardcoded paths')."),
            ],
            content: Annotated[
                str,
                Field(description="Full directive text — the rule to enforce."),
            ],
            priority: Annotated[
                int,
                Field(description="Priority (higher = more important, default 0)."),
            ] = 0,
            tags: Annotated[
                list[str] | None,
                Field(description="Tags for categorization."),
            ] = None,
            bank: Annotated[
                str | None,
                Field(description="Target bank. Defaults to first visible bank."),
            ] = None,
            ctx: Context = None,
        ) -> str:
            """Create a new directive (hard rule).

            Directives are injected into reasoning as constraints. Use sparingly
            for rules that must always be followed.
            """
            s = _get_store(ctx)
            if s is None or not s.ready:
                return "Error: Memory service not available."

            vis = _visibility(ctx)
            resolved_bank = bank or s.default_bank(vis)

            try:
                result = await s.create_directive(
                    resolved_bank,
                    name,
                    content,
                    priority=priority,
                    tags=tags,
                )
            except Exception as exc:
                return f"Error: {exc}"

            did = str(result.get("id", "?"))[:12]
            return f"Created directive '{name}' [id:{did}]"

        @server.tool()
        async def update_directive(
            directive_id: Annotated[
                str,
                Field(description="ID of the directive to update (from list_directives output)."),
            ],
            content: Annotated[
                str | None,
                Field(description="New directive text."),
            ] = None,
            priority: Annotated[
                int | None,
                Field(description="New priority."),
            ] = None,
            is_active: Annotated[
                bool | None,
                Field(description="Set active/inactive status."),
            ] = None,
            tags: Annotated[
                list[str] | None,
                Field(description="New tags (replaces existing)."),
            ] = None,
            bank: Annotated[
                str | None,
                Field(description="Bank containing the directive. Defaults to first visible bank."),
            ] = None,
            ctx: Context = None,
        ) -> str:
            """Update an existing directive.

            Use ``list_directives`` first to find the directive ID.
            """
            s = _get_store(ctx)
            if s is None or not s.ready:
                return "Error: Memory service not available."

            vis = _visibility(ctx)
            resolved_bank = bank or s.default_bank(vis)

            try:
                await s.update_directive(
                    resolved_bank,
                    directive_id,
                    content=content,
                    priority=priority,
                    is_active=is_active,
                    tags=tags,
                )
            except Exception as exc:
                return f"Error: {exc}"

            return f"Updated directive [id:{directive_id[:12]}]"

        @server.tool()
        async def delete_directive(
            directive_id: Annotated[
                str,
                Field(description="ID of the directive to delete (from list_directives output)."),
            ],
            bank: Annotated[
                str | None,
                Field(description="Bank containing the directive. Defaults to first visible bank."),
            ] = None,
            ctx: Context = None,
        ) -> str:
            """Delete a directive by ID.

            Use ``list_directives`` first to find the directive ID.
            This permanently removes the rule.
            """
            s = _get_store(ctx)
            if s is None or not s.ready:
                return "Error: Memory service not available."

            vis = _visibility(ctx)
            resolved_bank = bank or s.default_bank(vis)

            try:
                await s.delete_directive(resolved_bank, directive_id)
            except Exception as exc:
                return f"Error: {exc}"

            return f"Deleted directive [id:{directive_id[:12]}]"

        # ── Bank Profile Tools ───────────────────────────────────────────

        @server.tool()
        async def get_profile(
            bank: Annotated[
                str | None,
                Field(description="Bank to get profile for. Defaults to first visible bank."),
            ] = None,
            ctx: Context = None,
        ) -> str:
            """Read the bank profile — mission statement and personality disposition.

            Returns the bank's name, mission text, and disposition traits
            (skepticism, literalism, empathy on 1-5 scales).
            """
            s = _get_store(ctx)
            if s is None or not s.ready:
                return "Error: Memory service not available."

            vis = _visibility(ctx)
            resolved_bank = bank or s.default_bank(vis)

            try:
                profile = await s.get_bank_profile(resolved_bank)
            except Exception as exc:
                return f"Error: {exc}"

            if not profile:
                return f"No profile found for bank '{resolved_bank}'."

            lines = [f"Bank '{resolved_bank}' profile:"]
            for key, value in profile.items():
                lines.append(f"  {key}: {value}")
            return "\n".join(lines)

        @server.tool()
        async def set_mission(
            mission: Annotated[
                str,
                Field(description="New mission statement text for the bank."),
            ],
            bank: Annotated[
                str | None,
                Field(description="Target bank. Defaults to first visible bank."),
            ] = None,
            ctx: Context = None,
        ) -> str:
            """Update the bank's mission statement.

            The mission describes the bank's purpose and guides how memories
            are prioritized and interpreted.
            """
            s = _get_store(ctx)
            if s is None or not s.ready:
                return "Error: Memory service not available."

            vis = _visibility(ctx)
            resolved_bank = bank or s.default_bank(vis)

            try:
                await s.set_bank_mission(resolved_bank, mission)
            except Exception as exc:
                return f"Error: {exc}"

            return f"Updated mission for bank '{resolved_bank}'."

        @server.tool()
        async def set_disposition(
            skepticism: Annotated[
                int | None,
                Field(description="Skepticism level (1-5). Higher = more critical evaluation of claims."),
            ] = None,
            literalism: Annotated[
                int | None,
                Field(description="Literalism level (1-5). Higher = more literal interpretation."),
            ] = None,
            empathy: Annotated[
                int | None,
                Field(description="Empathy level (1-5). Higher = more emotionally attuned responses."),
            ] = None,
            bank: Annotated[
                str | None,
                Field(description="Target bank. Defaults to first visible bank."),
            ] = None,
            ctx: Context = None,
        ) -> str:
            """Tune the bank's personality disposition traits.

            Each trait is on a 1-5 scale. Only pass traits you want to change —
            omitted traits keep their current values.
            """
            s = _get_store(ctx)
            if s is None or not s.ready:
                return "Error: Memory service not available."

            vis = _visibility(ctx)
            resolved_bank = bank or s.default_bank(vis)

            try:
                await s.update_bank_disposition(
                    resolved_bank,
                    skepticism=skepticism,
                    literalism=literalism,
                    empathy=empathy,
                )
            except Exception as exc:
                return f"Error: {exc}"

            changed = []
            if skepticism is not None:
                changed.append(f"skepticism={skepticism}")
            if literalism is not None:
                changed.append(f"literalism={literalism}")
            if empathy is not None:
                changed.append(f"empathy={empathy}")
            return f"Updated disposition for bank '{resolved_bank}': {', '.join(changed)}"

    return server


# ── Internal helpers ──────────────────────────────────────────────────


def _is_after(item: dict, since: datetime) -> bool:
    """Check if an item was created/updated after the given timestamp."""
    for key in ("updated_at", "created_at", "timestamp"):
        ts = item.get(key)
        if ts is None:
            continue
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts)
            except ValueError:
                continue
        if isinstance(ts, datetime):
            # Make both aware or both naive for comparison
            if ts.tzinfo is None and since.tzinfo is not None:
                ts = ts.replace(tzinfo=timezone.utc)
            elif ts.tzinfo is not None and since.tzinfo is None:
                since = since.replace(tzinfo=timezone.utc)
            return ts >= since
    return True  # If no timestamp found, include it
