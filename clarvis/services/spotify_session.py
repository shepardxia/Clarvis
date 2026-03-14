"""Lazy SpotifySession singleton.

Provides a shared SpotifySession instance that initializes on first call
and re-attempts if previous init failed.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from clautify.dsl import SpotifySession

logger = logging.getLogger(__name__)

_session: SpotifySession | None = None


def get_spotify_session():
    """Lazy SpotifySession singleton. Re-attempts on each call if previous init failed."""
    global _session
    if _session is not None:
        return _session

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
        _session = session
    else:
        logger.warning("Spotify health check FAILED: %s", check.get("error", "unknown"))
        # Don't cache — next call will retry
    return session


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
