"""Memory command handlers — facts, models, observations."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import CommandHandlers

from ...formatters.memory import (
    fmt_bank_stats,
    fmt_facts,
    fmt_mental_models,
    fmt_observations,
    fmt_stale_models,
)

# --- Facts ---


def recall_memory(
    self: CommandHandlers,
    *,
    query: str,
    bank: str = "parletre",
    fact_type: str | None = None,
    tags: list[str] | None = None,
    **kw,
) -> str | dict:
    """Search memory for facts matching a query."""
    fact_types = [fact_type] if fact_type else None
    result = self._mem_op(lambda s: s.recall(query, bank=bank, fact_type=fact_types, tags=tags))
    if isinstance(result, dict) and "error" in result:
        return result
    results = result.get("results") or result.get("facts") or []
    if not results:
        return "No memories found."
    return f"Results:\n{fmt_facts(results)}"


def remember_fact(
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
        new_ids = result.get("new_ids", [])
        return f"Updated. Old: {id}, New: {', '.join(str(i) for i in new_ids)}"
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
    return f"{header}:\n{fmt_facts(items)}"


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
    self: CommandHandlers, *, query: str, bank: str = "parletre", tags: list[str] | None = None, **kw
) -> str | dict:
    """Search mental models by query and optional tags."""
    result = self._mem_op(lambda s: s.search_mental_models(query, bank=bank, tags=tags))
    if isinstance(result, dict) and "error" in result:
        return result
    models = result.get("results", []) if isinstance(result, dict) else result
    if not models:
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
    self: CommandHandlers, *, id: str, bank: str = "parletre", content: str | None = None, name: str | None = None, **kw
) -> str | dict:
    """Update a mental model's name or content."""
    result = self._mem_op(lambda s: s.update_mental_model(bank, id, content=content, name=name))
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
    content = result.get("content") or result.get("summary") or ""
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
    self: CommandHandlers, *, decisions: list[dict], fact_ids_to_mark: list[str], bank: str = "parletre", **kw
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
    result = self._mem_op(lambda s: s.apply_consolidation_decisions(bank, parsed, fact_ids_to_mark))
    if isinstance(result, dict) and "error" in result:
        return result
    created = result.get("created", 0) if isinstance(result, dict) else 0
    updated = result.get("updated", 0) if isinstance(result, dict) else 0
    deleted = result.get("deleted", 0) if isinstance(result, dict) else 0
    marked = result.get("marked", 0) if isinstance(result, dict) else len(fact_ids_to_mark)
    return (
        f"Consolidation applied: {created} created, {updated} updated, "
        f"{deleted} deleted, {marked} facts marked as consolidated."
    )


def stale_models(self: CommandHandlers, *, bank: str = "parletre", **kw) -> str | dict:
    """List mental models that need refreshing."""
    result = self._mem_op(lambda s: s.list_models_needing_refresh(bank))
    if isinstance(result, dict) and "error" in result:
        return result
    return fmt_stale_models(result)


COMMANDS: dict[str, str] = {
    "recall": "recall_memory",
    "remember": "remember_fact",
    "update_fact": "update_fact",
    "forget": "forget",
    "list_facts": "list_facts",
    "stats": "stats",
    "audit": "audit",
    "list_models": "list_models",
    "search_models": "search_models",
    "create_model": "create_model",
    "update_model": "update_model",
    "delete_model": "delete_model",
    "list_observations": "list_observations",
    "get_observation": "get_observation",
    "unconsolidated": "unconsolidated",
    "related_observations": "related_observations",
    "consolidate": "consolidate",
    "stale_models": "stale_models",
}
