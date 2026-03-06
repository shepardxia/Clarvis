"""Knowledge graph formatting helpers — entities, relations, search results."""

import json


def fmt_entities(entities: list[dict]) -> str:
    """Format entity list into numbered lines."""
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


def fmt_relations(rels: list[dict]) -> str:
    """Format relationship list into numbered lines."""
    if not rels:
        return "No relationships found."
    lines = []
    for i, r in enumerate(rels, 1):
        src = str(r.get("source_id", "?"))[:8]
        tgt = str(r.get("target_id", "?"))[:8]
        rel = r.get("relationship", "related_to")
        props = r.get("properties", {})
        prop_str = ""
        if props:
            prop_str = f" {props}"
        lines.append(f"  {i}. [{src}] --{rel}--> [{tgt}]{prop_str}")
    return "\n".join(lines)


def fmt_search_results(results: list[dict]) -> str:
    """Format knowledge search results into numbered lines."""
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
        if len(str(content)) > 300:
            content = str(content)[:297] + "..."
        lines.append(f"  {i}.{suffix} {content}")
    return f"Results ({len(results)}):\n" + "\n".join(lines)
