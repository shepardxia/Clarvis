"""Memory formatting helpers — facts, models, observations, stats."""


def fmt_facts(facts: list[dict]) -> str:
    """Format a list of fact dicts into numbered lines."""
    if not facts:
        return "No results."
    lines = []
    for i, fact in enumerate(facts, 1):
        fid = str(fact.get("id", "?"))
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


def fmt_mental_models(models: list[dict]) -> str:
    """Format mental models into numbered lines."""
    if not models:
        return "No mental models."
    lines = []
    for i, m in enumerate(models, 1):
        mid = str(m.get("id", "?"))
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


def fmt_observations(observations: list[dict]) -> str:
    """Format observations into numbered lines."""
    if not observations:
        return "No observations."
    lines = []
    for i, obs in enumerate(observations, 1):
        oid = str(obs.get("id", "?"))
        content = (obs.get("content") or obs.get("summary") or "")[:120]
        if len(obs.get("content", obs.get("summary", ""))) > 120:
            content += "..."
        tags = obs.get("tags", [])
        parts = [f"[id:{oid}]", content]
        if tags:
            parts.append(f"[tags: {', '.join(tags)}]")
        lines.append(f"  {i}. {' '.join(parts)}")
    return "\n".join(lines)


def fmt_stale_models(models: list[dict]) -> str:
    """Format stale models needing refresh."""
    if not models:
        return "No mental models need refreshing."
    lines = [f"{len(models)} models need refreshing:"]
    for m in models:
        mid = str(m.get("id", "?"))
        name = m.get("name", "unnamed")
        tags = m.get("tags", [])
        tag_str = f" [tags: {', '.join(tags)}]" if tags else ""
        lines.append(f"  - [id:{mid}] {name}{tag_str}")
    return "\n".join(lines)


def fmt_bank_stats(bank: str, stats: dict) -> str:
    """Format bank statistics as key-value lines."""
    if not stats:
        return f"No stats available for bank '{bank}'."
    lines = [f"Bank '{bank}' stats:"]
    for key, value in stats.items():
        lines.append(f"  {key}: {value}")
    return "\n".join(lines)
