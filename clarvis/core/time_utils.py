"""Shared time utilities."""

from datetime import datetime, timezone


def is_after(item: dict, since: datetime) -> bool:
    """Check if an item was created/updated after the given timestamp."""
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
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
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return ts >= since
    return True
