"""Memory command handlers — facts, models, observations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...formatters.memory import (
    fmt_bank_stats,
    fmt_facts,
    fmt_mental_models,
    fmt_observations,
    fmt_stale_models,
)

if TYPE_CHECKING:
    from . import CommandHandlers

_CONSOLIDATION_OBS_LIMIT = 500  # max observations fetched for update/delete validation

# --- Facts ---


def recall(
    self: CommandHandlers,
    *,
    query: str,
    bank: str = "parletre",
    fact_type: str | None = None,
    tags: list[str] | None = None,
    limit: int = 50,
    **kw,
) -> str | dict:
    """Search memory for facts matching a query."""
    fact_types = [fact_type] if fact_type else None
    result = self._mem_op(lambda s: s.recall(query, bank=bank, fact_type=fact_types, tags=tags))
    if isinstance(result, dict) and "error" in result:
        return result
    results = (result.get("results") or result.get("facts") or [])[:limit]
    if not results:
        return "No memories found."
    return f"Results:\n{fmt_facts(results, bank=bank)}"


def remember(
    self: CommandHandlers,
    *,
    text: str,
    fact_type: str = "world",
    bank: str = "parletre",
    entities: list[str] | None = None,
    confidence: float | None = None,
    tags: list[str] | None = None,
    **kw,
) -> str | dict:
    """Store a new fact in memory."""
    from clarvis.memory.store import FactInput

    fact = FactInput(
        fact_text=text, fact_type=fact_type, entities=entities or [], confidence=confidence, tags=tags or []
    )

    def _do(s):
        async def _run():
            ids = await s.store_facts([fact], bank=bank)
            return {"stored": len(ids), "fact_ids": ids}

        return _run()

    result = self._mem_op(_do)
    if isinstance(result, dict) and "error" in result:
        return result
    fact_ids = result.get("fact_ids", [])
    if not fact_ids:
        return "Stored (no fact IDs returned)."
    lines = [f"  [{fact_type}] id:{fid}" for fid in fact_ids]
    return "Stored:\n" + "\n".join(lines)


def update_fact(
    self: CommandHandlers,
    *,
    id: str,
    text: str | None = None,
    fact_type: str | None = None,
    confidence: float | None = None,
    bank: str = "parletre",
    **kw,
) -> str | dict:
    """Update an existing fact's text, type, or confidence."""
    if text is None:
        return {"error": "text is required for update"}
    result = self._mem_op(
        lambda s: s.update_fact(id, bank=bank, content=text, fact_type=fact_type, confidence=confidence)
    )
    if isinstance(result, dict) and "error" in result:
        return result
    if result.get("success"):
        return f"Updated fact {result.get('fact_id', id)} in place."
    return f"Update failed: {result.get('message', 'unknown error')}"


def forget(self: CommandHandlers, *, id: str, **kw) -> str | dict:
    """Delete a fact by ID."""
    result = self._mem_op(lambda s: s.delete_fact(id))
    if isinstance(result, dict) and "error" in result:
        return result
    return f"Forgotten: {id}"


def list_facts(
    self: CommandHandlers, *, bank: str = "parletre", fact_type: str | None = None, limit: int = 50, **kw
) -> str | dict:
    """List stored facts, optionally filtered by type."""
    result = self._mem_op(lambda s: s.list_facts(bank, fact_type=fact_type, limit=limit))
    if isinstance(result, dict) and "error" in result:
        return result
    items = result.get("items", []) if isinstance(result, dict) else result
    if not items:
        return "No memories found."
    total = result.get("total", len(items)) if isinstance(result, dict) else len(items)
    header = f"Showing {len(items)} of {total} facts"
    if fact_type:
        header += f" (type: {fact_type})"
    return f"{header}:\n{fmt_facts(items, bank=bank)}"


def get_fact(self: CommandHandlers, *, id: str, bank: str = "parletre", **kw) -> str | dict:
    """Get a single fact with full metadata."""
    result = self._mem_op(lambda s: s.get_fact(bank, id))
    if isinstance(result, dict) and "error" in result:
        return result
    if result is None:
        return f"Fact {id} not found in bank '{bank}'."
    ftype = result.get("fact_type") or result.get("type") or ""
    content = result.get("content") or result.get("text") or result.get("fact_text") or ""
    confidence = result.get("confidence")
    tags = result.get("tags", [])
    consolidated = result.get("consolidated_at")
    parts = [f"Fact [id:{id}] [bank:{bank}]"]
    if ftype:
        parts.append(f"Type: {ftype}")
    parts.append(f"Content: {content}")
    if confidence is not None:
        parts.append(f"Confidence: {confidence}")
    if tags:
        parts.append(f"Tags: {', '.join(tags)}")
    if consolidated:
        parts.append(f"Consolidated: {consolidated}")
    else:
        parts.append("Consolidated: no")
    return "\n".join(parts)


# --- Stats & audit ---


def stats(self: CommandHandlers, *, bank: str = "parletre", **kw) -> str | dict:
    """Show bank statistics (fact count, etc.)."""
    result = self._mem_op(lambda s: s.get_bank_stats(bank))
    if isinstance(result, dict) and "error" in result:
        return result
    return fmt_bank_stats(bank, result)


def audit(self: CommandHandlers, *, bank: str = "parletre", **kw) -> str | dict:
    """Show recent facts, observations, and models (last 24h)."""
    from datetime import datetime, timedelta, timezone

    from ...core.time_utils import is_after

    async def _do(s):
        since = datetime.now(timezone.utc) - timedelta(days=1)
        cap = 30
        facts_result = await s.list_facts(bank, limit=cap * 3)
        facts = facts_result.get("items", []) if isinstance(facts_result, dict) else facts_result
        recent_facts = [f for f in facts if is_after(f, since)][:cap]
        observations = await s.list_observations(bank, limit=cap * 3)
        recent_obs = [o for o in observations if is_after(o, since)][:cap]
        models = await s.list_mental_models(bank)
        recent_models = [m for m in models if is_after(m, since)][:cap]
        return {
            "since": since.isoformat(),
            "recent_facts": recent_facts,
            "recent_observations": recent_obs,
            "recent_models": recent_models,
        }

    result = self._mem_op(_do, timeout=60)
    if isinstance(result, dict) and "error" in result:
        return result

    since = result["since"]
    parts = []
    recent_facts = result["recent_facts"]
    parts.append(f"Facts since {since} ({len(recent_facts)}):")
    parts.append(fmt_facts(recent_facts) if recent_facts else "  (none)")
    recent_obs = result["recent_observations"]
    parts.append(f"\nObservations since {since} ({len(recent_obs)}):")
    parts.append(fmt_observations(recent_obs) if recent_obs else "  (none)")
    recent_models = result["recent_models"]
    parts.append(f"\nMental models since {since} ({len(recent_models)}):")
    parts.append(fmt_mental_models(recent_models) if recent_models else "  (none)")
    return "\n".join(parts)


# --- Mental models ---


def list_models(self: CommandHandlers, *, bank: str = "parletre", **kw) -> str | dict:
    """List all mental models."""
    result = self._mem_op(lambda s: s.list_mental_models(bank))
    if isinstance(result, dict) and "error" in result:
        return result
    if not result:
        return "No mental models."
    return f"Mental models ({len(result)}):\n{fmt_mental_models(result)}"


def search_models(
    self: CommandHandlers,
    *,
    query: str,
    bank: str = "parletre",
    tags: list[str] | None = None,
    tags_match: str = "any",
    **kw,
) -> str | dict:
    """Search mental models by query and optional tags (AND logic — both must match)."""
    result = self._mem_op(lambda s: s.search_mental_models(query, bank=bank, tags=tags, tags_match=tags_match))
    if isinstance(result, dict) and "error" in result:
        return result
    models = result.get("mental_models", []) if isinstance(result, dict) else result
    if not models:
        if tags:
            # Diagnose: was it the tags that narrowed to zero?
            without_tags = self._mem_op(lambda s: s.search_mental_models(query, bank=bank))
            if isinstance(without_tags, dict) and without_tags.get("mental_models"):
                n = len(without_tags["mental_models"])
                return (
                    f"No models matched query + tags={tags} (tags_match={tags_match}). "
                    f"{n} model(s) matched the query alone — try without tags."
                )
        return "No matching mental models."
    return f"Matching models ({len(models)}):\n{fmt_mental_models(models)}"


def create_model(
    self: CommandHandlers,
    *,
    name: str,
    content: str,
    source_query: str,
    bank: str = "parletre",
    tags: list[str] | None = None,
    **kw,
) -> str | dict:
    """Create a new mental model from a source query."""
    result = self._mem_op(lambda s: s.create_mental_model(bank, name, content, source_query, tags=tags))
    if isinstance(result, dict) and "error" in result:
        return result
    mid = str(result.get("id", "?"))
    return f"Created mental model '{name}' [id:{mid}]"


def update_model(
    self: CommandHandlers,
    *,
    id: str,
    bank: str = "parletre",
    content: str | None = None,
    name: str | None = None,
    tags: list[str] | None = None,
    **kw,
) -> str | dict:
    """Update a mental model's name, content, or tags."""
    result = self._mem_op(lambda s: s.update_mental_model(bank, id, content=content, name=name, tags=tags))
    if isinstance(result, dict) and "error" in result:
        return result
    return f"Updated mental model [id:{id}]"


def delete_model(self: CommandHandlers, *, id: str, bank: str = "parletre", **kw) -> str | dict:
    """Delete a mental model by ID."""
    result = self._mem_op(lambda s: s.delete_mental_model(bank, id))
    if isinstance(result, dict) and "error" in result:
        return result
    return f"Deleted mental model [id:{id}]"


# --- Observations & consolidation ---


def list_observations(self: CommandHandlers, *, bank: str = "parletre", limit: int = 50, **kw) -> str | dict:
    """List observations (consolidated fact summaries)."""
    result = self._mem_op(lambda s: s.list_observations(bank, limit=limit))
    if isinstance(result, dict) and "error" in result:
        return result
    if not result:
        return "No observations."
    return f"Observations ({len(result)}):\n{fmt_observations(result)}"


def get_observation(
    self: CommandHandlers, *, id: str, bank: str = "parletre", include_sources: bool = True, **kw
) -> str | dict:
    """Get a single observation with optional source facts."""
    result = self._mem_op(lambda s: s.get_observation(bank, id, include_source_facts=include_sources))
    if isinstance(result, dict) and "error" in result:
        return result
    if result is None:
        return f"Observation {id} not found."
    content = result.get("text") or result.get("content") or result.get("summary") or ""
    tags = result.get("tags", [])
    parts = [f"Observation [id:{id}]:", content]
    if tags:
        parts.append(f"Tags: {', '.join(tags)}")
    source_facts = result.get("source_facts") or result.get("source_memories") or []
    if source_facts:
        parts.append(f"\nSource facts ({len(source_facts)}):")
        parts.append(fmt_facts(source_facts))
    return "\n".join(parts)


def unconsolidated(self: CommandHandlers, *, bank: str = "parletre", limit: int = 100, **kw) -> str | dict:
    """List facts not yet consolidated into observations."""
    result = self._mem_op(lambda s: s.get_unconsolidated(bank, limit=limit))
    if isinstance(result, dict) and "error" in result:
        return result
    facts = result.get("facts", []) if isinstance(result, dict) else []
    if not facts:
        return f"No unconsolidated facts in bank '{bank}'."
    return f"{len(facts)} unconsolidated facts:\n{fmt_facts(facts)}"


def related_observations(self: CommandHandlers, *, fact_ids: list[str], bank: str = "parletre", **kw) -> str | dict:
    """Find observations related to a set of facts."""

    async def _do(s):
        fact_texts, fact_tags = [], []
        for fid in fact_ids:
            fact = await s.get_fact(bank, fid)
            if fact:
                fact_texts.append(fact.get("content") or fact.get("text") or fact.get("fact_text") or "")
                fact_tags.append(fact.get("tags") or [])
            else:
                fact_texts.append("")
                fact_tags.append([])
        return await s.get_related_observations(bank, fact_texts, fact_tags)

    result = self._mem_op(_do)
    if isinstance(result, dict) and "error" in result:
        return result
    observations = result.get("observations", []) if isinstance(result, dict) else []
    if not observations:
        return "No related observations found."
    return f"{len(observations)} related observations:\n{fmt_observations(observations)}"


def consolidate(
    self: CommandHandlers,
    *,
    decisions: list[dict],
    fact_ids_to_mark: list[str] | None = None,
    bank: str = "parletre",
    **kw,
) -> str | dict:
    """Apply consolidation decisions (create/update/delete observations)."""
    from clarvis.memory.store import ConsolidationDecision

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
        return {"error": f"Invalid decisions: {exc}"}

    if fact_ids_to_mark is None:
        fact_ids_to_mark = list({fid for d in parsed for fid in d.source_fact_ids})

    needs_observations = any(d.action in ("update", "delete") for d in parsed)

    async def _do(s):
        related = None
        if needs_observations:
            related = await s.list_observations(bank, limit=_CONSOLIDATION_OBS_LIMIT)
        return await s.apply_consolidation_decisions(bank, parsed, fact_ids_to_mark, related_observations=related)

    result = self._mem_op(_do)
    if isinstance(result, dict) and "error" in result:
        return result
    created = result.get("created", 0) if isinstance(result, dict) else 0
    updated = result.get("updated", 0) if isinstance(result, dict) else 0
    deleted = result.get("deleted", 0) if isinstance(result, dict) else 0
    marked = result.get("marked", 0) if isinstance(result, dict) else len(fact_ids_to_mark)
    skipped = result.get("skipped", 0) if isinstance(result, dict) else 0
    msg = (
        f"Consolidation applied: {created} created, {updated} updated, "
        f"{deleted} deleted, {marked} facts marked as consolidated."
    )
    if skipped:
        msg += f" ({skipped} skipped — observation ID not found)"
    return msg


def stale_models(self: CommandHandlers, *, bank: str = "parletre", **kw) -> str | dict:
    """List mental models that need refreshing."""
    result = self._mem_op(lambda s: s.list_models_needing_refresh(bank))
    if isinstance(result, dict) and "error" in result:
        return result
    return fmt_stale_models(result)


COMMANDS: list[str] = [
    "recall",
    "remember",
    "update_fact",
    "forget",
    "get_fact",
    "list_facts",
    "stats",
    "audit",
    "list_models",
    "search_models",
    "create_model",
    "update_model",
    "delete_model",
    "list_observations",
    "get_observation",
    "unconsolidated",
    "related_observations",
    "consolidate",
    "stale_models",
]
