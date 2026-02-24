"""Shared context formatting and JSONL transcript helpers.

Used by MCP tools, hook processor, and wakeup manager to avoid
duplicating weather/time/location/transcript formatting logic.
"""

import json
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Ambient context formatters
# ---------------------------------------------------------------------------


def weather_summary(state: dict | None) -> str | None:
    """Format weather state as ``"72F partly cloudy"``."""
    if not state or not state.get("temperature"):
        return None
    desc = state.get("description", "").lower()
    temp = state.get("temperature", "?")
    return f"{temp}F {desc}"


def time_summary(state: dict | None, fmt: str = "full") -> str | None:
    """Format time state.

    *fmt* controls output style:
    - ``"full"``: ``monday, february 24, 2:15pm`` (MCP / agent-facing)
    - ``"compact"``: ``Monday evening`` (short form)
    """
    if not state or not state.get("timestamp"):
        return None
    try:
        dt = datetime.fromisoformat(state["timestamp"])
    except (ValueError, KeyError):
        return None

    if fmt == "compact":
        hour = dt.hour
        if 5 <= hour < 12:
            period = "morning"
        elif 12 <= hour < 17:
            period = "afternoon"
        elif 17 <= hour < 21:
            period = "evening"
        else:
            period = "night"
        return f"{dt.strftime('%A')} {period}"

    # full
    return dt.strftime("%A, %B %-d, %-I:%M%p").lower()


def location_summary(state: dict | None) -> str | None:
    """Return city name from location state, or None."""
    if not state:
        return None
    city = state.get("city")
    return city if city else None


def now_playing_summary(get_session) -> str | None:
    """Return ``"♫ Title - Artist"`` if Spotify is actively playing.

    *get_session* is a callable returning a SpotifySession (or None).
    Sync — intended for ``run_in_executor``.
    """
    try:
        session = get_session()
        if session is None:
            return None
        state = session._executor.player.state
        if not state or not state.is_playing or state.is_paused:
            return None
        m = getattr(state, "track", None) and state.track.metadata
        if not m or not m.title:
            return None
        artist = session._executor._cache.name_for_uri(m.artist_uri) if m.artist_uri else None
        return f"♫ {m.title}" + (f" - {artist}" if artist else "")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# JSONL transcript parsing
# ---------------------------------------------------------------------------


def iter_transcript_messages(path: str | Path) -> list[dict]:
    """Parse a Claude Code JSONL transcript into a list of messages.

    Returns ``[{"role": "U"|"A", "text": str}, ...]`` in chronological order.
    Filters to user/assistant entries, flattens content arrays, and skips
    ``<system`` prefixed text blocks.
    """
    p = Path(path)
    if not p.exists():
        return []

    messages: list[dict] = []
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                entry_type = entry.get("type")
                if entry_type not in ("user", "assistant"):
                    continue

                content = entry.get("message", {}).get("content", "")

                # Flatten content arrays (skip tool_use, system reminders)
                if isinstance(content, list):
                    texts = [
                        c.get("text", "")
                        for c in content
                        if c.get("type") == "text" and not c.get("text", "").startswith("<system")
                    ]
                    content = " ".join(texts)

                if not content or content.startswith("<system"):
                    continue

                role = "U" if entry_type == "user" else "A"
                messages.append({"role": role, "text": content})
    except OSError:
        return []

    return messages


def format_message(msg: dict, max_len: int = 150) -> str:
    """Format a parsed transcript message as ``"U: truncated text..."``."""
    text = msg["text"][:max_len].replace("\n", " ").strip()
    return f"{msg['role']}: {text}"
