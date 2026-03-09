"""Lazy SpotifySession singleton.

Provides a shared SpotifySession instance that initializes on first call
and re-attempts if previous init failed.
"""

import logging

logger = logging.getLogger(__name__)

_session_cache: dict = {}


def get_spotify_session():
    """Lazy SpotifySession singleton. Re-attempts on each call if previous init failed."""
    if "instance" not in _session_cache:
        from clautify.dsl import SpotifySession

        session = SpotifySession.from_config(eager=False)
        # Apply max volume from Clarvis config
        try:
            from ..display.config import get_config

            session.max_volume = get_config().music.max_volume / 100
        except Exception:
            pass
        check = session.health_check()
        if check.get("authenticated"):
            logger.info("Spotify health check passed")
            _session_cache["instance"] = session
        else:
            logger.warning("Spotify health check FAILED: %s", check.get("error", "unknown"))
            # Don't cache — next call will retry
            return session
    return _session_cache["instance"]


def get_playback_state():
    """Get current Spotify playback state without reaching into clautify internals.

    Returns the player state object, or None if unavailable.
    """
    session = get_spotify_session()
    if session is None:
        return None
    try:
        return session._executor.player.state
    except (AttributeError, Exception):
        return None
