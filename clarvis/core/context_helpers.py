"""Shared context formatting helpers.

Single entry point: ``build_ambient_context(state)`` returns formatted
time, weather, location, and now-playing as a newline-joined string.
"""

from datetime import datetime


def build_ambient_context(state, include_paused: bool = False) -> str:
    """Build ambient context string from StateStore.

    Args:
        state: StateStore instance (has ``.get(key) -> dict``).
        include_paused: if True, include paused Spotify tracks.

    Returns formatted lines: time, weather (+location), now-playing.
    """
    getter = state.get if hasattr(state, "get") else (lambda _: {})
    parts: list[str] = []

    # Time
    time_state = getter("time")
    ts = _time_summary(time_state)
    parts.append(ts or datetime.now().astimezone().strftime("%A %H:%M"))

    # Weather + location
    ws = _weather_summary(getter("weather"))
    loc = _location_summary(getter("location"))
    if ws:
        parts.append(f"{ws} ({loc})" if loc else ws)
    elif loc:
        parts.append(loc)

    # Now playing
    np = _now_playing(include_paused=include_paused)
    if np:
        parts.append(np)

    return "\n".join(parts)


def _time_summary(state: dict | None) -> str | None:
    if not state or not state.get("timestamp"):
        return None
    try:
        dt = datetime.fromisoformat(state["timestamp"])
    except (ValueError, KeyError):
        return None
    return dt.strftime("%A, %B %-d, %-I:%M%p").lower()


def _weather_summary(state: dict | None) -> str | None:
    if not state or not state.get("temperature"):
        return None
    desc = state.get("description", "").lower()
    temp = state.get("temperature", "?")
    return f"{temp}F {desc}"


def _location_summary(state: dict | None) -> str | None:
    if not state:
        return None
    return state.get("city")


def _now_playing(include_paused: bool = False) -> str | None:
    try:
        from ..services.spotify_session import get_playback_state

        state = get_playback_state()
        if not state:
            return None
        if state.is_paused:
            if not include_paused:
                return None
            prefix = "♫ (paused)"
        elif state.is_playing:
            prefix = "♫"
        else:
            return None
        m = getattr(state, "track", None) and state.track.metadata
        if not m or not m.title:
            return None
        artist = m.artist_name or None
        line = f"{prefix} {m.title}" + (f" - {artist}" if artist else "")
        progress = _format_progress(state)
        return f"{line} {progress}" if progress else line
    except Exception:
        return None


def _format_progress(state) -> str | None:
    pos = state.position_as_of_timestamp
    dur = state.duration
    if not pos or not dur:
        return None
    pos_s, dur_s = int(pos) // 1000, int(dur) // 1000
    return f"[{pos_s // 60}:{pos_s % 60:02d}/{dur_s // 60}:{dur_s % 60:02d}]"
