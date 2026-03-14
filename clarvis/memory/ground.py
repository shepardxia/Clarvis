"""Memory grounding — build <memory_context> blocks for system prompt injection.

Composes session-start context from multiple layers in priority order:

1. **Authored grounding files** — curated prose in ``~/.clarvis/clarvis/grounding/*.md``,
   written by Clarvis during checkin (personality, directives, user profile, etc.).
2. **Core mental models** — always included (tagged ``core``).
3. **Bank stats** — compact summary of memory state.
4. **Recent facts** — latest experiences and world knowledge for recency signal.
5. **Recent observations** — consolidated insights from reflection.
6. **Extra mental models** — fill remaining token budget.

Falls back to mental-models-only if no grounding files exist (pre-first-checkin).
"""

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from clarvis.core.paths import agent_home

if TYPE_CHECKING:
    from clarvis.memory.store import MemoryStore

logger = logging.getLogger(__name__)

# Rough chars-per-token estimate for budget calculations.
_CHARS_PER_TOKEN = 4
_DEFAULT_TOKEN_BUDGET = 4096


async def build_memory_context(
    store: "MemoryStore",
    visibility: str,
    *,
    token_budget: int = _DEFAULT_TOKEN_BUDGET,
    grounding_dir: Path | str | None = None,
) -> str:
    """Build <memory_context> block from grounding files + Hindsight data.

    Composes from multiple sources in priority order:

    1. **Authored grounding files** — curated prose from ``grounding_dir``
       (``*.md`` files in sorted order). Written by Clarvis during checkin.
    2. **Core mental models** — always included (tagged ``core``).
    3. **Bank stats** — compact summary of memory state.
    4. **Recent facts** — latest experiences and world knowledge.
    5. **Recent observations** — consolidated insights from reflection.
    6. **Extra mental models** — fill remaining token budget.

    Falls back to mental-models-only if no grounding files exist (pre-first-checkin).

    Args:
        store: MemoryStore instance.
        visibility: "master" or "all" -- determines bank access.
        token_budget: Approximate token budget for the entire block.
        grounding_dir: Directory containing authored ``*.md`` grounding files.
            Defaults to ``~/.clarvis/clarvis/grounding/``.

    Returns:
        Formatted ``<memory_context>`` string for system prompt injection.
        Empty string if store is not ready and no grounding files exist.
    """
    if grounding_dir is None:
        grounding_dir = agent_home("clarvis") / "grounding"
    else:
        grounding_dir = Path(grounding_dir).expanduser()

    char_budget = token_budget * _CHARS_PER_TOKEN
    sections: list[str] = []
    chars_used = 0

    # ── 1. Authored grounding files (highest priority) ───────────
    grounding_text = _read_grounding_files(grounding_dir)
    if grounding_text:
        sections.append(grounding_text)
        chars_used += len(grounding_text)

    # ── 2–4. Hindsight data (mental models + stats) ──────────────
    if store is not None and store.ready:
        try:
            banks = store.visible_banks(visibility)
        except Exception:
            logger.debug("Failed to get visible banks", exc_info=True)
            banks = []

        for bank in banks:
            bank_lines = await _build_bank_section(
                store,
                bank,
                char_budget,
                chars_used,
            )
            if bank_lines:
                section = f"### {bank}\n\n" + "\n\n".join(bank_lines)
                sections.append(section)
                chars_used += len(section)

    if not sections:
        return ""

    body = "\n\n".join(sections)
    return f"<memory_context>\n{body}\n</memory_context>"


def _read_grounding_files(grounding_dir: Path) -> str:
    """Read all ``*.md`` files from grounding directory, sorted by name.

    Returns concatenated content, or empty string if directory doesn't exist
    or contains no markdown files.
    """
    if not grounding_dir.is_dir():
        return ""

    parts: list[str] = []
    for md_file in sorted(grounding_dir.glob("*.md")):
        try:
            content = md_file.read_text(encoding="utf-8").strip()
            if content:
                parts.append(content)
        except Exception:
            logger.debug("Failed to read grounding file %s", md_file, exc_info=True)

    return "\n\n".join(parts)


async def _build_bank_section(
    store: "MemoryStore",
    bank: str,
    char_budget: int,
    chars_used: int,
) -> list[str]:
    """Build formatted lines for a single bank.

    Priority order: core models → stats → recent facts → recent observations
    → extra models (fills remaining budget).
    """
    bank_lines: list[str] = []

    # Fetch all independent data in parallel.
    async def _core_models():
        try:
            return await store.list_mental_models(bank, tags=["core"], tags_match="any")
        except Exception:
            logger.debug("Failed to list core models for bank %s", bank, exc_info=True)
            return []

    async def _stats():
        try:
            return await store.get_bank_stats(bank)
        except Exception:
            logger.debug("Failed to get stats for bank %s", bank, exc_info=True)
            return None

    async def _facts():
        try:
            return await store.list_facts(bank, limit=10)
        except Exception:
            logger.debug("Failed to list facts for bank %s", bank, exc_info=True)
            return {}

    async def _observations():
        try:
            return await store.list_observations(bank, limit=5)
        except Exception:
            logger.debug("Failed to list observations for bank %s", bank, exc_info=True)
            return []

    async def _all_models():
        try:
            return await store.list_mental_models(bank, limit=50)
        except Exception:
            logger.debug("Failed to list models for bank %s", bank, exc_info=True)
            return []

    core_models, stats, fact_result, observations, all_models = await asyncio.gather(
        _core_models(),
        _stats(),
        _facts(),
        _observations(),
        _all_models(),
    )

    # Core models — always included.
    for model in core_models:
        entry = _format_model(model)
        if entry:
            bank_lines.append(entry)
            chars_used += len(entry)

    # Bank stats — compact summary.
    if stats:
        stat_line = _format_stats(bank, stats, len(all_models))
        if stat_line and chars_used + len(stat_line) <= char_budget:
            bank_lines.append(stat_line)
            chars_used += len(stat_line)

    # Recent facts — latest experiences and world knowledge.
    facts = fact_result.get("items", []) if isinstance(fact_result, dict) else []
    if facts:
        fact_lines = [x for x in (_format_fact(f) for f in facts) if x]
        if fact_lines:
            block = "**Recent facts**\n" + "\n".join(fact_lines)
            if chars_used + len(block) <= char_budget:
                bank_lines.append(block)
                chars_used += len(block)

    # Recent observations — consolidated insights.
    if observations:
        obs_lines = [x for x in (_format_observation(o) for o in observations) if x]
        if obs_lines:
            block = "**Recent observations**\n" + "\n".join(obs_lines)
            if chars_used + len(block) <= char_budget:
                bank_lines.append(block)
                chars_used += len(block)

    # Extra models — fill remaining budget.
    core_ids = {m.get("id") for m in core_models}
    for model in all_models:
        if model.get("id") in core_ids:
            continue
        entry = _format_model(model)
        if not entry:
            continue
        if chars_used + len(entry) > char_budget:
            break
        bank_lines.append(entry)
        chars_used += len(entry)

    return bank_lines


def _format_stats(bank: str, stats: dict, model_count: int) -> str:
    """Format bank stats as a compact one-liner.

    Example: ``parletre: 48 facts (29 world, 14 experience), 5 observations, 3 models``
    """
    node_counts = stats.get("node_counts") or {}
    total_obs = stats.get("total_observations", 0)

    # Fact counts by type (exclude observations from node_counts)
    fact_types = {k: v for k, v in node_counts.items() if k != "observation"}
    total_facts = sum(fact_types.values())

    parts: list[str] = []
    if total_facts:
        type_breakdown = ", ".join(f"{v} {k}" for k, v in sorted(fact_types.items(), key=lambda x: -x[1]))
        parts.append(f"{total_facts} facts ({type_breakdown})")
    if total_obs:
        parts.append(f"{total_obs} observations")
    if model_count:
        parts.append(f"{model_count} models")

    if not parts:
        return ""
    return f"*{bank}: {', '.join(parts)}*"


def _format_model(model: dict) -> str:
    """Format a single mental model dict into a readable block.

    Returns empty string if the model has no usable content.
    """
    name = model.get("name", "").strip()
    content = model.get("content", "").strip()

    if not content:
        return ""

    tags = model.get("tags") or []
    tag_str = f" [{', '.join(tags)}]" if tags else ""

    header = f"**{name}**{tag_str}" if name else ""
    if header:
        return f"{header}\n{content}"
    return content


def _format_fact(fact: dict) -> str:
    """Format a single fact as a compact one-liner for grounding context."""
    text = fact.get("text", "").strip()
    if not text:
        return ""
    fact_type = fact.get("fact_type", "")
    date = fact.get("occurred_start") or fact.get("mentioned_at") or ""
    if date:
        date = date[:10]  # YYYY-MM-DD
    prefix = f"[{fact_type}]" if fact_type else ""
    suffix = f" ({date})" if date else ""
    return f"- {prefix} {text}{suffix}".strip()


def _format_observation(obs: dict) -> str:
    """Format a single observation as a compact one-liner for grounding context."""
    text = obs.get("text", "").strip()
    if not text:
        return ""
    count = obs.get("proof_count", 1)
    suffix = f" (x{count})" if count and count > 1 else ""
    return f"- {text}{suffix}"
