"""Shared context formatting helpers.

Used by MCP tools and wakeup manager to avoid duplicating
weather/time/location formatting logic.
"""

from datetime import datetime

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
# Composed ambient context
# ---------------------------------------------------------------------------


def build_ambient_context(
    state_getter,
    now_playing: str | None = None,
    time_state: dict | None = None,
) -> list[str]:
    """Build ambient context lines from state.

    Returns a list of formatted strings: time, weather (+location), now playing.

    Args:
        state_getter: callable that takes a key and returns a state dict.
        now_playing: pre-fetched now-playing string (from ``now_playing_summary``).
        time_state: if provided, uses ``time_summary(time_state, "full")`` instead
            of local clock. Pass the result of ``refresh.refresh_time()`` for accuracy.
    """
    parts: list[str] = []

    # Time
    if time_state:
        ts = time_summary(time_state, fmt="full")
        parts.append(ts or "time: unavailable")
    else:
        parts.append(datetime.now().astimezone().strftime("%A %H:%M"))

    # Weather + location (combined)
    ws = weather_summary(state_getter("weather"))
    loc = location_summary(state_getter("location"))
    if ws:
        line = ws
        if loc:
            line += f" ({loc})"
        parts.append(line)
    elif loc:
        parts.append(loc)

    # Now playing
    if now_playing:
        parts.append(now_playing)

    return parts
