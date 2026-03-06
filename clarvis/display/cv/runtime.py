"""On-block runtime evaluation — matches context against on-block cases."""

from __future__ import annotations

from .specs import OnBlock


def evaluate_on_blocks(blocks: list[OnBlock], context: dict) -> dict:
    """Evaluate on-blocks against context, return merged overrides."""
    result: dict = {}
    for block in blocks:
        value = context.get(block.context_key)
        if value is None:
            continue
        for case in block.cases:
            if _matches(case.match, value):
                result.update(case.overrides)
    return result


def _matches(pattern: str, value: object) -> bool:
    """Check if a value matches a pattern string."""
    # Range match: "0..6"
    if ".." in pattern:
        parts = pattern.split("..", 1)
        try:
            lo, hi = float(parts[0]), float(parts[1])
            return lo <= float(value) <= hi
        except (ValueError, TypeError):
            return False

    # Bool match
    if pattern in ("true", "false"):
        return str(value).lower() == pattern

    # Exact string match
    return str(value) == pattern
