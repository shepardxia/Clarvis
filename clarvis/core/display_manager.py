"""Manages display rendering and frame output."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Optional

from .colors import StatusColors

if TYPE_CHECKING:
    from ..core.state import StateStore
    from ..widget.renderer import FrameRenderer
    from ..widget.socket_server import WidgetSocketServer


class DisplayManager:
    """Manages display rendering loop and frame output."""

    def __init__(
        self,
        renderer: FrameRenderer,
        socket_server: WidgetSocketServer,
        fps: int = 2,
    ):
        self.renderer = renderer
        self.socket_server = socket_server
        self.fps = fps

        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._state_store: Optional[StateStore] = None

    def render_frame(
        self,
        status: str,
        context_percent: float,
        whimsy_verb: Optional[str] = None,
    ) -> dict:
        """Render a single frame and return the output dict.

        Returns a dict with three fields:
        - rows: list of strings (one per grid row)
        - cell_colors: 2D list of ANSI 256 color codes per cell
        - theme_color: [r, g, b] floats for border and default text color
        """
        with self._lock:
            color_def = StatusColors.get(status)
            rows, cell_colors = self.renderer.render_grid(context_percent, whimsy_verb)
            return {
                "rows": rows,
                "cell_colors": cell_colors,
                "theme_color": list(color_def.rgb),
            }

    def push_frame(self, output: dict) -> None:
        """Push frame to socket."""
        self.socket_server.push_frame(output)

    def tick(self) -> None:
        """Advance renderer animation state."""
        with self._lock:
            self.renderer.tick()

    def set_status(self, status: str) -> None:
        """Update renderer status."""
        with self._lock:
            self.renderer.set_status(status)

    def set_weather(self, weather_type: str, intensity: float, wind_speed: float) -> None:
        """Update renderer weather."""
        with self._lock:
            self.renderer.set_weather(weather_type, intensity, wind_speed)

    def set_fps(self, fps: int) -> None:
        """Update render FPS. Takes effect on the next loop iteration."""
        self.fps = max(1, fps)

    def _update_voice_text(self) -> None:
        """Calculate and apply voice text reveal state from state store."""
        if not self._state_store:
            return
        voice_data = self._state_store.get("voice_text")
        if not voice_data or not voice_data.get("active"):
            self.renderer.clear_voice_text()
            return

        full_text = voice_data.get("full_text", "")
        tts_started = voice_data.get("tts_started_at", 0)
        tts_speed = voice_data.get("tts_speed", 150)
        streaming = voice_data.get("streaming", False)

        if streaming or tts_started <= 0:
            # Still streaming from Claude — show all text received so far
            reveal_chars = len(full_text)
        else:
            # TTS in progress — reveal at word boundaries synced with speech
            elapsed = time.time() - tts_started
            # Compensate for TTS subprocess startup delay (~250ms)
            elapsed = max(0, elapsed - 0.25)
            chars_per_sec = tts_speed * 5.0 / 60.0
            target_chars = min(int(elapsed * chars_per_sec), len(full_text))
            # Snap to word boundary to avoid revealing partial words
            if target_chars < len(full_text):
                space_idx = full_text.rfind(" ", 0, target_chars + 1)
                reveal_chars = space_idx + 1 if space_idx > 0 else target_chars
            else:
                reveal_chars = len(full_text)

        self.renderer.set_voice_text(full_text, reveal_chars)

    def _loop(self, get_state: callable) -> None:
        """Display rendering loop.

        All state reads and rendering happen under a single lock acquisition
        to prevent mid-frame tearing (e.g., stale voice text with new status).
        """
        while self._running:
            interval = 1.0 / self.fps
            start = time.time()

            self.tick()
            with self._lock:
                self._update_voice_text()
                status, context_percent, whimsy_verb = get_state()
                color_def = StatusColors.get(status)
                rows, cell_colors = self.renderer.render_grid(context_percent, whimsy_verb)
                output = {
                    "rows": rows,
                    "cell_colors": cell_colors,
                    "theme_color": list(color_def.rgb),
                }
            self.push_frame(output)

            elapsed = time.time() - start
            sleep_time = max(0, interval - elapsed)
            time.sleep(sleep_time)

    def start(self, get_state: callable, state_store: Optional[StateStore] = None) -> None:
        """Start the display loop.

        Args:
            get_state: Callable returning (status, context_percent, whimsy_verb)
            state_store: Optional StateStore for voice text reveal calculation
        """
        if self._thread is not None and self._thread.is_alive():
            return

        self._state_store = state_store
        self._running = True
        self._thread = threading.Thread(
            target=self._loop,
            args=(get_state,),
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the display loop."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
