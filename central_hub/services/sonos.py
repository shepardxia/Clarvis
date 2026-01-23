"""Sonos speaker control via SoCo library."""

import soco


class SonosController:
    """
    Controller for Sonos speakers on the local network.

    Uses SoCo library: https://github.com/SoCo/SoCo
    """

    def __init__(self):
        self._speakers: dict[str, soco.SoCo] = {}

    def _ensure_discovered(self) -> None:
        """Discover speakers if not already cached."""
        if not self._speakers:
            self.discover()

    def _get_speaker(self, name: str | None = None) -> soco.SoCo | None:
        """Get a speaker by name, or the first one found."""
        self._ensure_discovered()

        if not self._speakers:
            return None

        if name:
            return self._speakers.get(name)

        return next(iter(self._speakers.values()))

    def discover(self) -> list[str]:
        """
        Discover all Sonos speakers on the network.

        Returns:
            List of speaker names
        """
        speakers = soco.discover(timeout=5)

        if not speakers:
            self._speakers = {}
            return []

        self._speakers = {s.player_name: s for s in speakers}
        return list(self._speakers.keys())

    def now_playing(self, speaker: str | None = None) -> dict:
        """
        Get current track info from a speaker.

        Args:
            speaker: Speaker name (default: first found)

        Returns:
            Track info dict with title, artist, album, position, duration, state
        """
        s = self._get_speaker(speaker)
        if not s:
            return {"error": "No speaker found"}

        try:
            track = s.get_current_track_info()
            transport = s.get_current_transport_info()

            return {
                "speaker": s.player_name,
                "title": track.get("title", "Unknown"),
                "artist": track.get("artist", "Unknown"),
                "album": track.get("album", "Unknown"),
                "position": track.get("position", "0:00:00"),
                "duration": track.get("duration", "0:00:00"),
                "state": transport.get("current_transport_state", "UNKNOWN"),
            }
        except Exception as e:
            return {"error": str(e)}

    def play(self, speaker: str | None = None) -> str:
        """Start playback on a speaker."""
        s = self._get_speaker(speaker)
        if not s:
            return "No speaker found"

        try:
            s.play()
            return f"Playing on {s.player_name}"
        except Exception as e:
            return f"Error: {e}"

    def pause(self, speaker: str | None = None) -> str:
        """Pause playback on a speaker."""
        s = self._get_speaker(speaker)
        if not s:
            return "No speaker found"

        try:
            s.pause()
            return f"Paused {s.player_name}"
        except Exception as e:
            return f"Error: {e}"

    def next_track(self, speaker: str | None = None) -> str:
        """Skip to next track on a speaker."""
        s = self._get_speaker(speaker)
        if not s:
            return "No speaker found"

        try:
            s.next()
            return f"Skipped to next track on {s.player_name}"
        except Exception as e:
            return f"Error: {e}"

    def previous_track(self, speaker: str | None = None) -> str:
        """Go to previous track on a speaker."""
        s = self._get_speaker(speaker)
        if not s:
            return "No speaker found"

        try:
            s.previous()
            return f"Previous track on {s.player_name}"
        except Exception as e:
            return f"Error: {e}"

    def volume(self, speaker: str | None = None, level: int | None = None) -> str:
        """
        Get or set volume on a speaker.

        Args:
            speaker: Speaker name (default: first found)
            level: Volume level 0-100 (omit to get current)

        Returns:
            Current or new volume level message
        """
        s = self._get_speaker(speaker)
        if not s:
            return "No speaker found"

        try:
            if level is not None:
                level = max(0, min(100, level))
                s.volume = level
                return f"{s.player_name} volume set to {level}"
            else:
                return f"{s.player_name} volume: {s.volume}"
        except Exception as e:
            return f"Error: {e}"

    def mute(self, speaker: str | None = None, mute: bool | None = None) -> str:
        """
        Get or set mute state on a speaker.

        Args:
            speaker: Speaker name (default: first found)
            mute: True to mute, False to unmute (omit to toggle)

        Returns:
            Current mute state message
        """
        s = self._get_speaker(speaker)
        if not s:
            return "No speaker found"

        try:
            if mute is None:
                s.mute = not s.mute
            else:
                s.mute = mute

            state = "muted" if s.mute else "unmuted"
            return f"{s.player_name} {state}"
        except Exception as e:
            return f"Error: {e}"


# Global controller instance
_controller: SonosController | None = None


def get_controller() -> SonosController:
    """Get or create the global Sonos controller."""
    global _controller
    if _controller is None:
        _controller = SonosController()
    return _controller
